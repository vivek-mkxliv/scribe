"""Dynamic, repo-derived documentation structure: sections containing pages.

Replaces a single fixed list of doc ids per `AudienceMode` (`constants.DOC_SUITE`) with a
structure that's proposed by an LLM planning call, grounded in real signals from the extracted
`GraphContext` (entry points, languages, module count) instead of a round, made-up number of
pages. The result can be compared against a user-supplied plan (`--doc-plan-file`), is cached
per repo content hash so an unchanged repo never re-derives it, and is persisted alongside the
generated docs (`.scribe_plan.json`) for quick human reference.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from scribe.constants import DOC_SUITE, AudienceMode
from scribe.extraction.models import GraphContext
from scribe.providers.llm_client import LLMClient

# Present in the planning prompt only -- lets callers (including tests) detect a planning call
# without inspecting the full rendered template.
PLANNER_MARKER = "SCRIBE DOCUMENTATION STRUCTURE PLANNER"

# Same purpose as PLANNER_MARKER, but for a revision call (see `derive_doc_plan_revision_via_llm`).
REVISION_MARKER = "SCRIBE DOCUMENTATION STRUCTURE REVISION"


class DocPlanContractError(RuntimeError):
    """Raised when a doc plan (LLM-proposed or user-supplied) doesn't parse/validate."""


def _extract_json_object(text: str) -> str:
    """Best-effort extraction of a single JSON object from a raw LLM response.

    Local models frequently ignore "output ONLY JSON" instructions and wrap the object in
    prose and/or a markdown code fence (observed in practice: "Here is the proposed
    documentation structure in JSON format:\n```json\n{...}\n```"). Strips a leading fence if
    present, then locates the first "{" and its brace-balanced matching "}" -- respecting JSON
    string literals so a "{" inside quoted text doesn't throw off the count -- and returns just
    that slice. Falls back to the original (stripped) text if no "{" is found, so `json.loads`
    still produces its own clear error rather than this silently swallowing a truly empty reply.
    """
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z]*\n?", "", stripped)
        stripped = re.sub(r"\n?```\s*$", "", stripped)

    start = stripped.find("{")
    if start == -1:
        return stripped

    depth = 0
    in_string = False
    escape = False
    for index in range(start, len(stripped)):
        char = stripped[index]
        if in_string:
            if escape:
                escape = False
            elif char == "\\":
                escape = True
            elif char == '"':
                in_string = False
            continue
        if char == '"':
            in_string = True
        elif char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return stripped[start : index + 1]
    return stripped[start:]


@dataclass
class DocPage:
    id: str  # relative path from output_dir, e.g. "user-guides/01-gui.md"
    title: str
    description: str = ""
    # Real repo-relative file paths this page is grounded in (from the Knowledge Graph), used
    # for per-page content staleness detection -- NOT required, and never invented if unknown.
    sources: list[str] = field(default_factory=list)


@dataclass
class DocSection:
    id: str
    title: str
    pages: list[DocPage] = field(default_factory=list)
    description: str = ""
    # Why THIS section has THIS many pages, citing a concrete signal (package/entry-point/CLI
    # subcommand count) -- forces the planner to justify each section individually instead of
    # only the plan as a whole, which is what actually prevents uniform, arbitrary page counts.
    rationale: str = ""


@dataclass
class DocPlan:
    """A finalized documentation structure for one generation run."""

    mode: AudienceMode
    sections: list[DocSection] = field(default_factory=list)
    rationale: str = ""

    @property
    def doc_ids(self) -> list[str]:
        """Flattened, ordered list of page ids -- what `writer`/`manifest` actually consume."""
        return [page.id for section in self.sections for page in section.pages]

    def to_prompt_text(self) -> str:
        """Render the plan as instructions for the generation prompt."""
        lines: list[str] = []
        for section in self.sections:
            header = f"### Section: {section.title}"
            if section.description:
                header += f" -- {section.description}"
            lines.append(header)
            for page in section.pages:
                lines.append(f'- (doc="{page.id}") {page.title}: {page.description}'.rstrip(": "))
        return "\n".join(lines)

    def to_json_dict(self) -> dict:
        return {
            "mode": self.mode.value,
            "rationale": self.rationale,
            "sections": [
                {
                    "id": section.id,
                    "title": section.title,
                    "description": section.description,
                    "rationale": section.rationale,
                    "pages": [
                        {
                            "id": page.id,
                            "title": page.title,
                            "description": page.description,
                            "sources": page.sources,
                        }
                        for page in section.pages
                    ],
                }
                for section in self.sections
            ],
        }

    def to_json(self) -> str:
        return json.dumps(self.to_json_dict(), indent=2)

    @staticmethod
    def from_json_dict(payload: dict, *, mode: AudienceMode | None = None) -> DocPlan:
        try:
            resolved_mode = AudienceMode(payload.get("mode") or (mode.value if mode else None))
            sections = []
            for raw_section in payload["sections"]:
                pages = [
                    DocPage(
                        id=p["id"],
                        title=p["title"],
                        description=p.get("description", ""),
                        sources=list(p.get("sources", []) or []),
                    )
                    for p in raw_section["pages"]
                ]
                sections.append(
                    DocSection(
                        id=raw_section["id"],
                        title=raw_section["title"],
                        description=raw_section.get("description", ""),
                        rationale=raw_section.get("rationale", ""),
                        pages=pages,
                    )
                )
        except (KeyError, TypeError, ValueError) as exc:
            raise DocPlanContractError(f"Malformed doc plan payload: {exc}") from exc

        if not sections or not any(section.pages for section in sections):
            raise DocPlanContractError("Doc plan has no sections/pages.")

        seen: set[str] = set()
        for doc_id in (page.id for section in sections for page in section.pages):
            if not doc_id.endswith(".md"):
                raise DocPlanContractError(f"Doc id '{doc_id}' must end in .md")
            if doc_id in seen:
                raise DocPlanContractError(f"Duplicate doc id in plan: {doc_id}")
            seen.add(doc_id)

        return DocPlan(mode=resolved_mode, sections=sections, rationale=payload.get("rationale", ""))

    @staticmethod
    def from_json(text: str, *, mode: AudienceMode | None = None) -> DocPlan:
        try:
            payload = json.loads(_extract_json_object(text))
        except json.JSONDecodeError as exc:
            snippet = text[:200].replace("\n", "\\n")
            raise DocPlanContractError(
                f"Doc plan response wasn't valid JSON: {exc}. Got: {snippet!r}"
            ) from exc
        return DocPlan.from_json_dict(payload, mode=mode)


def heuristic_doc_plan(mode: AudienceMode) -> DocPlan:
    """Zero-cost, deterministic fallback: one section wrapping the previous fixed doc list.

    Used for `--dry-run` (which must never make a real LLM call) and as the last-resort
    fallback if the LLM-backed planner still fails validation after a retry.
    """
    pages = [
        DocPage(id=doc_id, title=doc_id.removesuffix(".md").replace("_", " ").title())
        for doc_id in DOC_SUITE[mode]
    ]
    return DocPlan(
        mode=mode,
        sections=[DocSection(id="general", title="Documentation", pages=pages)],
        rationale="Heuristic fallback structure (fixed per-mode doc list, not repo-derived).",
    )


def derive_doc_plan_via_llm(
    client: LLMClient,
    model: str,
    project_context: str,
    graph_context: GraphContext,
    mode: AudienceMode,
    on_status: Callable[[str], None] | None = None,
    cli_surface_text: str = "",
    user_notes_text: str = "",
) -> DocPlan:
    """Ask the LLM to propose a documentation structure grounded in `graph_context`.

    Retries once (re-prompting with the parse error) on a malformed response, then falls back
    to `heuristic_doc_plan` rather than failing the whole run over a structure-planning hiccup.
    """
    from scribe.generation.prompt_builder import build_planning_prompt  # local: avoids an import cycle

    def status(message: str) -> None:
        if on_status:
            on_status(message)

    prompt = build_planning_prompt(project_context, graph_context, mode, cli_surface_text, user_notes_text)
    response = client.complete(prompt, model)
    try:
        return DocPlan.from_json(response, mode=mode)
    except DocPlanContractError as exc:
        status(f"Doc plan response was invalid ({exc}); asking the model to retry once.")
        followup = (
            f"{prompt}\n\n---PREVIOUS RESPONSE (INVALID)---\n{response}\n\n---INSTRUCTIONS---\n"
            f"Your previous response did not parse as the required JSON contract: {exc}. "
            "Resend ONLY the corrected JSON object, nothing else."
        )
        retry_response = client.complete(followup, model)
        try:
            return DocPlan.from_json(retry_response, mode=mode)
        except DocPlanContractError as retry_exc:
            status(f"Doc plan retry also failed ({retry_exc}); using the heuristic fallback structure.")
            return heuristic_doc_plan(mode)


def derive_doc_plan_revision_via_llm(
    client: LLMClient,
    model: str,
    project_context: str,
    graph_context: GraphContext,
    mode: AudienceMode,
    current_plan: DocPlan,
    current_justification: str,
    revision_request: str,
    on_status: Callable[[str], None] | None = None,
    cli_surface_text: str = "",
) -> DocPlan:
    """Ask the LLM to revise `current_plan` per a freeform `revision_request`.

    Retries once on a malformed response, like `derive_doc_plan_via_llm`. Unlike that function,
    there's NO heuristic fallback here -- silently discarding the user's real, already-generated
    structure in favor of a generic one on a parse failure would be a much worse surprise than
    just failing the revision outright and asking them to retry.
    """
    from scribe.generation.prompt_builder import build_revision_prompt  # local: avoids an import cycle

    def status(message: str) -> None:
        if on_status:
            on_status(message)

    prompt = build_revision_prompt(
        project_context,
        graph_context,
        mode,
        current_plan,
        current_justification,
        revision_request,
        cli_surface_text,
    )
    response = client.complete(prompt, model)
    try:
        return DocPlan.from_json(response, mode=mode)
    except DocPlanContractError as exc:
        status(f"Revision response was invalid ({exc}); asking the model to retry once.")
        followup = (
            f"{prompt}\n\n---PREVIOUS RESPONSE (INVALID)---\n{response}\n\n---INSTRUCTIONS---\n"
            f"Your previous response did not parse as the required JSON contract: {exc}. "
            "Resend ONLY the corrected JSON object, nothing else."
        )
        retry_response = client.complete(followup, model)
        return DocPlan.from_json(retry_response, mode=mode)  # let a 2nd failure propagate


def reconcile_doc_plan(
    recommended: DocPlan,
    user_plan: DocPlan | None,
    on_conflict: Callable[[DocPlan, DocPlan], DocPlan] | None = None,
) -> DocPlan:
    """Decide which plan wins when a user-supplied plan differs from the recommended one.

    No user plan -> recommended. Identical doc ids -> recommended, without asking (they agree).
    Otherwise: ask via `on_conflict` if given (interactive callers); default to the user's
    explicit input otherwise, consistent with "explicit input beats an auto suggestion"
    elsewhere in this codebase (CLI flag > config file > built-in default).
    """
    if user_plan is None:
        return recommended
    if user_plan.doc_ids == recommended.doc_ids:
        return recommended
    if on_conflict is not None:
        return on_conflict(recommended, user_plan)
    return user_plan


def load_user_doc_plan(path: Path, *, mode: AudienceMode) -> DocPlan:
    """Load and validate a user-authored plan file (JSON), e.g. a hand-edited `.scribe_plan.json`."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise DocPlanContractError(f"Couldn't read doc plan file '{path}': {exc}") from exc
    except json.JSONDecodeError as exc:
        raise DocPlanContractError(f"Doc plan file '{path}' isn't valid JSON: {exc}") from exc
    return DocPlan.from_json_dict(payload, mode=mode)


def _cache_path(cache_dir: Path, repo_hash: str, mode: AudienceMode) -> Path:
    return cache_dir / "doc_plans" / f"{repo_hash}_{mode.value}.json"


def load_cached_doc_plan(cache_dir: Path, repo_hash: str, mode: AudienceMode) -> DocPlan | None:
    path = _cache_path(cache_dir, repo_hash, mode)
    if not path.exists():
        return None
    try:
        return DocPlan.from_json_dict(json.loads(path.read_text(encoding="utf-8")), mode=mode)
    except (OSError, DocPlanContractError, json.JSONDecodeError):
        return None


def store_cached_doc_plan(cache_dir: Path, repo_hash: str, mode: AudienceMode, plan: DocPlan) -> None:
    path = _cache_path(cache_dir, repo_hash, mode)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(plan.to_json(), encoding="utf-8")
