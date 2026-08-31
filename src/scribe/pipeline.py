"""Orchestrates the four-stage S.C.R.I.B.E. pipeline end-to-end."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scribe.config import ScribeConfig
from scribe.extraction import extractor
from scribe.extraction.cache import compute_repo_hash
from scribe.extraction.extractor import GraphifyyMissingAction
from scribe.extraction.models import GraphContext
from scribe.generation import chunking, qa, writer
from scribe.generation.doc_plan import (
    DocPlan,
    derive_doc_plan_via_llm,
    heuristic_doc_plan,
    load_cached_doc_plan,
    load_user_doc_plan,
    reconcile_doc_plan,
    store_cached_doc_plan,
)
from scribe.generation.prompt_builder import (
    build_prompt,
    build_prompt_with_digest_text,
    build_repair_followup,
)
from scribe.generation.tokens import estimate_token_count
from scribe.project import manifest
from scribe.providers import llm_client

StatusCallback = Callable[[str], None]
DocPlanConflictCallback = Callable[[DocPlan, DocPlan], DocPlan]

# Progressively smaller module caps tried until the assembled prompt fits `token_budget`.
_DIGEST_MODULE_CAPS = (None, 150, 75, 30, 10)


class GenerationFailedError(RuntimeError):
    """Raised when the LLM output still fails validation after all repair attempts."""


class OverwriteConfirmationRequiredError(RuntimeError):
    """Raised when generation would overwrite existing files in `output_dir` and `assume_yes` wasn't set.

    Callers (the CLI) should list `existing_files`, confirm, and retry with
    `dataclasses.replace(config, assume_yes=True)`.
    """

    def __init__(self, existing_files: list[Path]) -> None:
        self.existing_files = existing_files
        names = ", ".join(p.name for p in existing_files)
        super().__init__(
            f"Would overwrite {len(existing_files)} existing file(s): {names}. Re-run with --yes to proceed."
        )


@dataclass
class DriftReport:
    up_to_date: bool
    reason: str


class CostConfirmationRequiredError(RuntimeError):
    """Raised when a run would exceed the token budget and `assume_yes` wasn't set.

    Callers (the CLI) should present `estimated_tokens`/`token_budget` to the user and,
    on confirmation, retry with `dataclasses.replace(config, assume_yes=True)`.
    """

    def __init__(self, estimated_tokens: int, token_budget: int, *, chunked: bool) -> None:
        self.estimated_tokens = estimated_tokens
        self.token_budget = token_budget
        self.chunked = chunked
        reason = (
            "chunked map-reduce generation (multiple LLM calls)" if chunked else "a single oversized call"
        )
        super().__init__(
            f"Estimated ~{estimated_tokens} tokens (budget {token_budget}) via {reason}. "
            "Re-run with --yes to proceed."
        )


def _noop_status(_message: str) -> None:
    return None


def _build_bounded_prompt(
    project_context: str,
    graph_context: GraphContext,
    doc_plan: DocPlan,
    token_budget: int,
    on_status: StatusCallback,
) -> tuple[str, int, bool]:
    """Assemble the prompt, shrinking the graph digest until it fits `token_budget`.

    Returns `(prompt, estimated_tokens, still_over_budget)` -- the caller decides what
    "still over budget even at the smallest digest" should mean (currently: require
    `--yes` confirmation, same as the chunked path).
    """
    prompt = ""
    token_count = 0
    for cap in _DIGEST_MODULE_CAPS:
        prompt = build_prompt(project_context, graph_context, doc_plan, max_graph_modules=cap)
        token_count = estimate_token_count(prompt)
        if token_count <= token_budget:
            if cap is not None:
                on_status(f"Graph digest truncated to {cap} modules to fit the {token_budget}-token budget.")
            return prompt, token_count, False
    on_status(
        f"Prompt is ~{token_count} tokens, still over the {token_budget}-token budget "
        "even at the smallest digest size."
    )
    return prompt, token_count, True


def _resolve_doc_plan(
    config: ScribeConfig,
    client: llm_client.LLMClient,
    graph_context: GraphContext,
    project_context: str,
    repo_hash: str,
    status: StatusCallback,
    on_doc_plan_conflict: DocPlanConflictCallback | None,
) -> DocPlan:
    """Resolve the finalized doc plan for a real (non-dry-run) generation run.

    Reuses a cached plan for this exact repo content hash + mode when available (so an
    unchanged repo never re-derives it); otherwise makes one LLM planning call and caches the
    result. If `config.doc_plan_file` is set, reconciles it against the recommended plan
    (identical -> no fuss; different -> `on_doc_plan_conflict` decides, defaulting to the
    user's file when running non-interactively). Persists the finalized plan to
    `output_dir/.scribe_plan.json` for quick human reference and reuse as a future
    `--doc-plan-file`.
    """
    recommended = None
    if not config.refresh_plan:
        recommended = load_cached_doc_plan(config.cache_dir, repo_hash, config.mode)
    if recommended is not None:
        status("Using cached documentation plan (repo unchanged).")
    else:
        status("Deriving a documentation structure for this repo...")
        recommended = derive_doc_plan_via_llm(
            client, config.model, project_context, graph_context, config.mode, on_status=status
        )
        store_cached_doc_plan(config.cache_dir, repo_hash, config.mode, recommended)

    user_plan = load_user_doc_plan(config.doc_plan_file, mode=config.mode) if config.doc_plan_file else None
    finalized = reconcile_doc_plan(recommended, user_plan, on_doc_plan_conflict)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / ".scribe_plan.json").write_text(finalized.to_json(), encoding="utf-8")
    return finalized


def _generate_with_repair(
    client: llm_client.LLMClient,
    prompt: str,
    model: str,
    expected_doc_ids: list[str],
    max_repair_attempts: int,
    on_status: StatusCallback,
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> dict[str, str]:
    """Call the LLM, validating (structure + QA) and re-prompting on failure.

    Returns `{doc_id: body}` once both the marker-structure validation and the
    QA pass (mermaid validity, dead links, placeholders) pass. Raises
    `GenerationFailedError` if issues remain after `max_repair_attempts`
    follow-up rounds.
    """
    conversation_prompt = prompt
    last_issue_description = "unknown error"

    for attempt in range(max_repair_attempts + 1):
        response = client.complete(conversation_prompt, model, temperature=temperature, max_tokens=max_tokens)
        validation = writer.validate_sections(response, expected_doc_ids)

        if not validation.ok:
            last_issue_description = validation.describe()
            on_status(f"Validation failed (attempt {attempt + 1}): {last_issue_description}")
        else:
            qa_report = qa.review_documents(validation.found)
            if qa_report.ok:
                return validation.found
            last_issue_description = qa_report.describe()
            on_status(f"QA issues found (attempt {attempt + 1}): {last_issue_description}")

        if attempt == max_repair_attempts:
            break

        followup = build_repair_followup(last_issue_description)
        conversation_prompt = (
            f"{prompt}\n\n---PREVIOUS RESPONSE (INVALID)---\n{response}\n\n---INSTRUCTIONS---\n{followup}"
        )

    raise GenerationFailedError(
        f"LLM output still invalid after {max_repair_attempts} repair attempt(s): {last_issue_description}"
    )


def run(
    config: ScribeConfig,
    on_status: StatusCallback | None = None,
    *,
    on_graphifyy_missing: Callable[[], GraphifyyMissingAction] | None = None,
    on_graphifyy_failed: Callable[[str, str], bool] | None = None,
    on_doc_plan_conflict: DocPlanConflictCallback | None = None,
) -> list[Path]:
    """Run context extraction -> plan resolution -> prompt assembly -> LLM call -> file writing.

    Returns the list of file paths written to `config.output_dir`.
    """
    status = on_status or _noop_status

    skip_incremental_shortcut = config.dry_run or config.doc_plan_file is not None or config.refresh_plan
    if config.incremental and not skip_incremental_shortcut:
        repo_hash = compute_repo_hash(config.repo_path)
        if manifest.is_up_to_date(config.output_dir, repo_hash, config.mode.value):
            status("Docs already up to date (repo unchanged since last generation); skipping.")
            cached_plan = load_cached_doc_plan(config.cache_dir, repo_hash, config.mode)
            doc_ids = cached_plan.doc_ids if cached_plan else heuristic_doc_plan(config.mode).doc_ids
            return manifest.existing_doc_files(config.output_dir, doc_ids)

    # 1. Context Extraction
    graph_context = extractor.extract_context(
        config.repo_path,
        use_cache=config.use_cache,
        refresh_cache=config.refresh_cache,
        force_native=config.force_native_extractor,
        cache_dir=config.cache_dir,
        on_status=status,
        on_graphifyy_missing=on_graphifyy_missing,
        on_graphifyy_failed=on_graphifyy_failed,
    )
    project_context = extractor.build_project_context(config.repo_path)
    repo_hash = compute_repo_hash(config.repo_path)

    # 2. Prompt Assembly (preliminary): a heuristic (non-LLM) plan is used purely to estimate
    # token count / chunking need, so a cost-confirmation abort never pays for a real planning
    # call it didn't need. The doc plan's own text is a tiny fraction of the full prompt (the
    # graph digest dominates), so this estimate is a safe approximation of the real plan's size.
    preliminary_plan = heuristic_doc_plan(config.mode)
    full_prompt = build_prompt(project_context, graph_context, preliminary_plan, max_graph_modules=None)
    full_tokens = estimate_token_count(full_prompt)
    needs_chunking = config.chunked or full_tokens > config.token_budget

    if config.dry_run:
        if needs_chunking:
            status(
                f"Repo digest is ~{full_tokens} tokens (budget {config.token_budget}); a real run "
                "would use chunked map-reduce generation (skipped here -- dry-run makes no LLM calls)."
            )
            prompt = full_prompt
        else:
            prompt, _tokens, _over = _build_bounded_prompt(
                project_context, graph_context, preliminary_plan, config.token_budget, status
            )
        preview_path = config.output_dir / "_dry_run_prompt.md"
        config.output_dir.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(prompt, encoding="utf-8")
        return [preview_path]

    if needs_chunking and not config.assume_yes:
        raise CostConfirmationRequiredError(full_tokens, config.token_budget, chunked=True)

    # 3. Documentation Structure Planning: resolved now that we know the run is actually
    # proceeding (cached, or exactly one LLM call -- see `_resolve_doc_plan`).
    client = llm_client.build_client(config.provider, config.api_key, config.base_url)
    doc_plan = _resolve_doc_plan(
        config, client, graph_context, project_context, repo_hash, status, on_doc_plan_conflict
    )
    expected_doc_ids = doc_plan.doc_ids

    # 4. LLM Orchestration (validates structure + QA, auto-repairing on failure)
    if needs_chunking:
        status(f"Repo digest ~{full_tokens} tokens exceeds the {config.token_budget}-token budget; chunking.")
        digest_text = chunking.build_chunked_digest(client, config.model, graph_context, status)
        prompt = build_prompt_with_digest_text(project_context, digest_text, doc_plan)
    else:
        prompt, final_tokens, still_over_budget = _build_bounded_prompt(
            project_context, graph_context, doc_plan, config.token_budget, status
        )
        if still_over_budget and not config.assume_yes:
            raise CostConfirmationRequiredError(final_tokens, config.token_budget, chunked=False)

    documents = _generate_with_repair(
        client,
        prompt,
        config.model,
        expected_doc_ids,
        config.max_repair_attempts,
        status,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
    )

    # 5. File System Writing
    # Only ask when output_dir has same-named files scribe doesn't already own (no manifest at
    # all, e.g. hand-written docs or a first run pointed at an existing folder). Once a manifest
    # exists, these files are scribe's own prior output, so regenerating never re-prompts.
    if not config.assume_yes and manifest.load_manifest(config.output_dir) is None:
        already_there = manifest.existing_doc_files(config.output_dir, expected_doc_ids)
        if already_there:
            raise OverwriteConfirmationRequiredError(already_there)

    written = writer.write_documents(documents, config.output_dir, expected_doc_ids)
    manifest.write_manifest(config.output_dir, repo_hash, config.mode.value, expected_doc_ids)
    return written


def check_drift(config: ScribeConfig, on_status: StatusCallback | None = None) -> DriftReport:
    """Compare the current repo hash against `output_dir`'s manifest -- no extraction, no LLM call.

    Safe for CI: `scribe generate --check` uses this to fail a build when generated docs are
    stale relative to source, without spending any tokens.
    """
    status = on_status or _noop_status
    manifest_data = manifest.load_manifest(config.output_dir)
    if manifest_data is None:
        status("No manifest found; docs have never been generated (or predate incremental tracking).")
        return DriftReport(up_to_date=False, reason="no manifest found in output_dir")

    if manifest_data.mode != config.mode.value:
        return DriftReport(
            up_to_date=False,
            reason=f"manifest was generated for mode '{manifest_data.mode}', not '{config.mode.value}'",
        )

    repo_hash = compute_repo_hash(config.repo_path)
    if manifest_data.repo_hash != repo_hash:
        return DriftReport(up_to_date=False, reason="repo content has changed since the docs were generated")

    missing = [doc_id for doc_id in manifest_data.doc_ids if not (config.output_dir / doc_id).exists()]
    if missing:
        return DriftReport(
            up_to_date=False, reason=f"tracked doc(s) missing from output_dir: {', '.join(missing)}"
        )

    return DriftReport(up_to_date=True, reason="repo unchanged since the last generation")
