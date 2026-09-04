"""Orchestrates the four-stage S.C.R.I.B.E. pipeline end-to-end."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from scribe.config import ScribeConfig
from scribe.constants import AudienceMode
from scribe.extraction import extractor
from scribe.extraction.cache import compute_paths_hash, compute_repo_hash, repo_identity_key
from scribe.extraction.cli_surface import build_cli_surface_text
from scribe.extraction.extractor import GraphifyyMissingAction
from scribe.extraction.models import GraphContext
from scribe.generation import chunking, writer
from scribe.generation.doc_plan import (
    DocPage,
    DocPlan,
    DocPlanContractError,
    derive_doc_plan_revision_via_llm,
    derive_doc_plan_via_llm,
    heuristic_doc_plan,
    load_cached_doc_plan,
    load_user_doc_plan,
    reconcile_doc_plan,
    store_cached_doc_plan,
)
from scribe.generation.justification import JUSTIFICATION_FILENAME, render_justification_markdown
from scribe.generation.page_writer import GenerationFailedError, generate_pages
from scribe.generation.prompt_builder import build_page_prompt
from scribe.generation.tokens import estimate_token_count
from scribe.project import manifest
from scribe.project.notes import load_scribe_notes
from scribe.project.org_context import load_org_context
from scribe.providers import llm_client

StatusCallback = Callable[[str], None]
DocPlanConflictCallback = Callable[[DocPlan, DocPlan], DocPlan]

# Progressively smaller module caps tried until a representative per-page prompt fits `token_budget`.
_DIGEST_MODULE_CAPS = (None, 150, 75, 30, 10)

__all__ = [
    "CostConfirmationRequiredError",
    "DriftReport",
    "GenerationFailedError",
    "NoExistingPlanError",
    "OverwriteConfirmationRequiredError",
    "check_drift",
    "revise_doc_plan",
    "run",
]


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


def _build_bounded_digest_text(
    project_context: str,
    graph_context: GraphContext,
    doc_plan: DocPlan,
    token_budget: int,
    on_status: StatusCallback,
    cli_surface_text: str = "",
    org_context_text: str = "",
) -> tuple[str, int, bool]:
    """Pick a graph-digest size that fits `token_budget` for a REPRESENTATIVE per-page prompt.

    Per-page generation means every page's prompt shares the same digest text, so this is
    computed once per run (not once per page) and reused. Sizing is checked against the doc
    plan's longest page description as a worst-case stand-in for "a real page's prompt".
    Returns `(digest_text, estimated_tokens, still_over_budget)`.
    """
    pages = [page for section in doc_plan.sections for page in section.pages]
    representative_page = max(pages, key=lambda p: len(p.description), default=None) or DocPage(
        id="placeholder.md", title="Placeholder", description=""
    )

    digest_text = ""
    token_count = 0
    for cap in _DIGEST_MODULE_CAPS:
        digest_text = graph_context.to_prompt_text(max_modules=cap)
        prompt = build_page_prompt(
            project_context,
            digest_text,
            doc_plan,
            representative_page,
            cli_surface_text=cli_surface_text,
            org_context_text=org_context_text,
        )
        token_count = estimate_token_count(prompt)
        if token_count <= token_budget:
            if cap is not None:
                on_status(f"Graph digest truncated to {cap} modules to fit the {token_budget}-token budget.")
            return digest_text, token_count, False
    on_status(
        f"A representative per-page prompt is ~{token_count} tokens, still over the "
        f"{token_budget}-token budget even at the smallest digest size."
    )
    return digest_text, token_count, True


def _load_durable_plan(output_dir: Path, mode: AudienceMode) -> DocPlan | None:
    """Read back this run's own prior `.scribe_plan.json`, if one exists and still parses.

    This is the file meant to be committed alongside the generated docs (see `manifest.py`'s
    module docstring) -- reading it back here is what makes the plan genuinely durable across
    machines/clones, not just cached locally under `~/.scribe_cache` (which a teammate's fresh
    clone or a CI runner won't have).
    """
    path = output_dir / ".scribe_plan.json"
    if not path.exists():
        return None
    try:
        return load_user_doc_plan(path, mode=mode)
    except DocPlanContractError:
        return None


def _resolve_doc_plan(
    config: ScribeConfig,
    client: llm_client.LLMClient,
    graph_context: GraphContext,
    project_context: str,
    plan_cache_key: str,
    status: StatusCallback,
    on_doc_plan_conflict: DocPlanConflictCallback | None,
    cli_surface_text: str = "",
) -> DocPlan:
    """Resolve the finalized doc plan for a real (non-dry-run) generation run.

    Tried in order (first hit wins), unless `--refresh-plan` is passed: (1) this run's own
    prior `output_dir/.scribe_plan.json` -- the repo-durable copy meant to be committed, so a
    teammate's fresh clone or a CI runner reuses the exact same structure instead of
    re-deriving its own; (2) the user-level cache keyed by stable repo identity (see
    `extraction.cache.repo_identity_key`), a same-machine optimization for before the first
    commit; (3) one LLM planning call. Either way, the documentation STRUCTURE stays stable
    across regenerations and isn't reshuffled/renamed on every content change. If
    `config.doc_plan_file` is set, reconciles it against the recommended plan (identical -> no
    fuss; different -> `on_doc_plan_conflict` decides, defaulting to the user's file when
    running non-interactively). Persists the finalized plan back to `output_dir/.scribe_plan.json`,
    and -- only when the structure was actually just derived by the LLM (a true first run, or
    `--refresh-plan`) -- (re)writes `scribe-doc-suite-justification.md` explaining why.
    """
    recommended = None
    plan_file = config.output_dir / ".scribe_plan.json"
    had_prior_plan = plan_file.exists()
    freshly_derived = False
    if not config.refresh_plan:
        recommended = _load_durable_plan(config.output_dir, config.mode)
        if recommended is not None:
            status("Using this repo's committed documentation plan (.scribe_plan.json).")
        else:
            recommended = load_cached_doc_plan(config.cache_dir, plan_cache_key, config.mode)
            if recommended is not None:
                status("Using cached documentation plan (structure stays stable across regenerations).")
    if recommended is None:
        status("Deriving a documentation structure for this repo...")
        recommended = derive_doc_plan_via_llm(
            client,
            config.model,
            project_context,
            graph_context,
            config.mode,
            on_status=status,
            cli_surface_text=cli_surface_text,
            user_notes_text=load_scribe_notes(config.repo_path),
        )
        store_cached_doc_plan(config.cache_dir, plan_cache_key, config.mode, recommended)
        freshly_derived = True

    user_plan = load_user_doc_plan(config.doc_plan_file, mode=config.mode) if config.doc_plan_file else None
    finalized = reconcile_doc_plan(recommended, user_plan, on_doc_plan_conflict)

    config.output_dir.mkdir(parents=True, exist_ok=True)
    plan_file.write_text(finalized.to_json(), encoding="utf-8")
    if freshly_derived:
        # Only touch the justification doc when the structure was actually (re)derived --
        # routine reuse of the durable/cached plan means nothing changed, so there's nothing
        # new to explain.
        event_label = "Structure re-derived via --refresh-plan" if had_prior_plan else "Initial generation"
        _write_justification(config.output_dir, finalized, event_label=event_label)
    return finalized


def _write_justification(
    output_dir: Path, plan: DocPlan, *, event_label: str, event_detail: str = ""
) -> None:
    path = output_dir / JUSTIFICATION_FILENAME
    previous_markdown = path.read_text(encoding="utf-8") if path.exists() else None
    path.write_text(
        render_justification_markdown(
            plan, previous_markdown=previous_markdown, event_label=event_label, event_detail=event_detail
        ),
        encoding="utf-8",
    )


def _partition_stale_pages(
    config: ScribeConfig,
    pages: list[DocPage],
    status: StatusCallback,
) -> tuple[list[DocPage], dict[str, str], dict[str, str]]:
    """Split `pages` into ones that need regenerating vs. ones whose sources haven't changed.

    Returns `(stale_pages, reused_documents, page_hashes)`:
    - `stale_pages`: the pages to actually send through `generate_pages` (an LLM call each).
    - `reused_documents`: `{doc_id: body}` read straight from the existing file in `output_dir`
      for pages whose sources are unchanged -- no LLM call made for these.
    - `page_hashes`: the `{doc_id: hash}` map to persist in the new manifest for every page
      that has one (reused pages carry their existing hash forward; stale pages get their
      current sources hash computed up front, since `page.sources` are repo files, not
      something regenerating the page itself would change).

    A page is only ever treated as unchanged when it explicitly lists `sources` (real repo file
    paths from the knowledge graph, populated by the planner) AND the hash of those paths
    matches the last recorded one AND the page's file still exists in `output_dir`. A page with
    no `sources`, or whose listed files no longer exist, is always stale -- this is meant to
    fail safe toward "regenerate", never silently skip something on uncertain grounds. Disabled
    entirely (every page treated as stale) when `--no-incremental` is passed.
    """
    if not config.incremental:
        return pages, {}, {}

    previous = manifest.load_manifest(config.output_dir)
    previous_hashes = previous.page_hashes if previous else {}

    stale_pages: list[DocPage] = []
    reused_documents: dict[str, str] = {}
    page_hashes: dict[str, str] = {}

    for page in pages:
        sources_hash = compute_paths_hash(config.repo_path, page.sources) if page.sources else None
        existing_path = config.output_dir / page.id
        if (
            sources_hash is not None
            and previous_hashes.get(page.id) == sources_hash
            and existing_path.exists()
        ):
            try:
                # `write_documents` always appends a trailing "\n" to the stored body; undo
                # that here so re-writing the reused body doesn't accumulate an extra newline
                # on every skip cycle.
                reused_documents[page.id] = existing_path.read_text(encoding="utf-8").removesuffix("\n")
                page_hashes[page.id] = sources_hash
                continue
            except OSError:
                pass  # fall through and treat it as stale instead
        stale_pages.append(page)
        if sources_hash is not None:
            page_hashes[page.id] = sources_hash

    if reused_documents:
        status(
            f"{len(reused_documents)} page(s) unchanged (sources unchanged since last run), "
            f"skipping regeneration: {', '.join(sorted(reused_documents))}."
        )
    return stale_pages, reused_documents, page_hashes


def run(
    config: ScribeConfig,
    on_status: StatusCallback | None = None,
    *,
    on_graphifyy_missing: Callable[[], GraphifyyMissingAction] | None = None,
    on_graphifyy_failed: Callable[[str, str], bool] | None = None,
    on_doc_plan_conflict: DocPlanConflictCallback | None = None,
) -> list[Path]:
    """Run context extraction -> plan resolution -> per-page generation -> file writing.

    Each page in the finalized doc plan gets its own LLM call (see
    `generation/page_writer.py`) rather than one call for the whole suite, so a page's content
    depth isn't capped by splitting one output-token budget across every document. Returns the
    list of file paths written to `config.output_dir`.
    """
    status = on_status or _noop_status

    skip_incremental_shortcut = config.dry_run or config.doc_plan_file is not None or config.refresh_plan
    if config.incremental and not skip_incremental_shortcut:
        repo_hash = compute_repo_hash(config.repo_path)
        if manifest.is_up_to_date(config.output_dir, repo_hash, config.mode.value):
            status("Docs already up to date (repo unchanged since last generation); skipping.")
            cached_plan = load_cached_doc_plan(
                config.cache_dir, repo_identity_key(config.repo_path), config.mode
            )
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
    cli_surface_text = build_cli_surface_text(config.repo_path)
    org_context_text = load_org_context(config.repo_path)

    # 2. Prompt Assembly (preliminary): a heuristic (non-LLM) plan and its longest page are used
    # purely to estimate a representative per-page prompt's size, so a cost-confirmation abort
    # never pays for a real planning call it didn't need.
    preliminary_plan = heuristic_doc_plan(config.mode)
    digest_text, full_tokens, digest_over_budget = _build_bounded_digest_text(
        project_context,
        graph_context,
        preliminary_plan,
        config.token_budget,
        status,
        cli_surface_text,
        org_context_text,
    )
    needs_chunking = config.chunked or digest_over_budget

    if config.dry_run:
        if needs_chunking:
            status(
                f"Repo digest is ~{full_tokens} tokens (budget {config.token_budget}); a real run "
                "would use chunked map-reduce generation (skipped here -- dry-run makes no LLM calls)."
            )
        preview_page = next(
            (page for section in preliminary_plan.sections for page in section.pages),
            DocPage(id="placeholder.md", title="Placeholder", description=""),
        )
        preview_prompt = build_page_prompt(
            project_context,
            digest_text,
            preliminary_plan,
            preview_page,
            cli_surface_text=cli_surface_text,
            org_context_text=org_context_text,
        )
        preview_prompt = (
            f"(Preview of page 1 of {len(preliminary_plan.doc_ids)} -- per-page generation makes "
            f"one LLM call like this per page in a real run.)\n\n{preview_prompt}"
        )
        preview_path = config.output_dir / "_dry_run_prompt.md"
        config.output_dir.mkdir(parents=True, exist_ok=True)
        preview_path.write_text(preview_prompt, encoding="utf-8")
        return [preview_path]

    if needs_chunking and not config.assume_yes:
        raise CostConfirmationRequiredError(full_tokens, config.token_budget, chunked=True)

    # 3. Documentation Structure Planning: resolved now that we know the run is actually
    # proceeding (cached, or exactly one LLM call -- see `_resolve_doc_plan`).
    client = llm_client.build_client(config.provider, config.api_key, config.base_url)
    doc_plan = _resolve_doc_plan(
        config,
        client,
        graph_context,
        project_context,
        repo_identity_key(config.repo_path),
        status,
        on_doc_plan_conflict,
        cli_surface_text,
    )
    expected_doc_ids = doc_plan.doc_ids

    # 4. Per-page LLM Orchestration (one call per page; see `generation/page_writer.py` for the
    # repair loop, truncation-continuation, and token-budget-escalation fallbacks each page gets).
    if needs_chunking:
        status(f"Repo digest ~{full_tokens} tokens exceeds the {config.token_budget}-token budget; chunking.")
        digest_text = chunking.build_chunked_digest(client, config.model, graph_context, status)

    all_pages = [page for section in doc_plan.sections for page in section.pages]
    stale_pages, reused_documents, page_hashes = _partition_stale_pages(config, all_pages, status)
    status(
        f"Generating {len(stale_pages)} page(s), one LLM call each (plus repair/fallback attempts as needed)."
    )

    def _prompt_for_page(page: DocPage) -> str:
        return build_page_prompt(
            project_context,
            digest_text,
            doc_plan,
            page,
            cli_surface_text=cli_surface_text,
            org_context_text=org_context_text,
        )

    documents, failed_page_ids = generate_pages(
        client,
        config.model,
        stale_pages,
        _prompt_for_page,
        config.max_repair_attempts,
        status,
        temperature=config.temperature,
        max_tokens=config.max_tokens,
        all_doc_ids=expected_doc_ids,
    )
    documents.update(reused_documents)
    for failed_id in failed_page_ids:
        # Never record a placeholder's sources hash as "done" -- retry it again next run.
        page_hashes.pop(failed_id, None)
    if failed_page_ids:
        status(
            f"{len(failed_page_ids)} of {len(stale_pages)} regenerated page(s) fell back to a "
            f"placeholder: {', '.join(failed_page_ids)}."
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
    manifest.write_manifest(
        config.output_dir, repo_hash, config.mode.value, expected_doc_ids, page_hashes=page_hashes
    )
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


class NoExistingPlanError(DocPlanContractError):
    """Raised by `revise_doc_plan` when no prior `.scribe_plan.json` exists to revise."""


def revise_doc_plan(
    config: ScribeConfig,
    revision_request: str,
    on_status: StatusCallback | None = None,
) -> DocPlan:
    """Revise this repo's existing, committed documentation structure per a freeform request.

    Requires a prior `.scribe_plan.json` (run `scribe generate` at least once first) -- raises
    `NoExistingPlanError` otherwise. Combines the current plan, its justification history (so
    the model doesn't undo still-valid past reasoning), any standing notes in `scribe.notes.md`,
    and `revision_request` into one LLM call (see `doc_plan.derive_doc_plan_revision_via_llm`).

    Writes the revised `.scribe_plan.json` and appends a dated entry to
    `scribe-doc-suite-justification.md`, but does NOT regenerate page content or touch the
    manifest -- run `scribe generate` afterward to apply the new structure: new/changed pages
    regenerate normally (no recorded sources hash yet), and pages removed from the plan simply
    stop being tracked, but their old files are left in place rather than deleted automatically.
    """
    status = on_status or _noop_status

    current_plan = _load_durable_plan(config.output_dir, config.mode)
    if current_plan is None:
        raise NoExistingPlanError(
            f"No existing plan found at '{config.output_dir / '.scribe_plan.json'}' -- run "
            "`scribe generate` at least once before requesting a revision."
        )

    justification_path = config.output_dir / JUSTIFICATION_FILENAME
    current_justification = (
        justification_path.read_text(encoding="utf-8") if justification_path.exists() else ""
    )

    notes_text = load_scribe_notes(config.repo_path)
    combined_request = revision_request
    if notes_text and not notes_text.startswith("No standing notes"):
        combined_request = f"{revision_request}\n\nStanding team notes (scribe.notes.md):\n{notes_text}"

    graph_context = extractor.extract_context(
        config.repo_path,
        use_cache=config.use_cache,
        refresh_cache=config.refresh_cache,
        force_native=config.force_native_extractor,
        cache_dir=config.cache_dir,
        on_status=status,
    )
    project_context = extractor.build_project_context(config.repo_path)
    cli_surface_text = build_cli_surface_text(config.repo_path)

    client = llm_client.build_client(config.provider, config.api_key, config.base_url)
    status("Revising the documentation structure...")
    revised = derive_doc_plan_revision_via_llm(
        client,
        config.model,
        project_context,
        graph_context,
        config.mode,
        current_plan,
        current_justification,
        combined_request,
        on_status=status,
        cli_surface_text=cli_surface_text,
    )

    config.output_dir.mkdir(parents=True, exist_ok=True)
    (config.output_dir / ".scribe_plan.json").write_text(revised.to_json(), encoding="utf-8")
    _write_justification(
        config.output_dir, revised, event_label="Revision requested", event_detail=revision_request
    )
    store_cached_doc_plan(config.cache_dir, repo_identity_key(config.repo_path), config.mode, revised)
    return revised
