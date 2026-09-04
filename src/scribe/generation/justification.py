"""Renders `scribe-doc-suite-justification.md` -- a human-readable explanation of doc structure decisions.

`.scribe_plan.json` carries a machine-readable `rationale` per plan/section, but that's not
something a teammate reviewing the repo would ever open. This module turns those same fields
into a dedicated, committed markdown file: a "Current Structure" section (regenerated fresh from
whatever plan is live right now) plus an append-only "Revision History" log (one dated entry per
structure (re)derivation, so the reasoning behind past decisions isn't lost when the structure
changes later -- the actual "long-term memory" piece for a tool meant to maintain a repo's docs
over its whole lifetime, not just produce them once).
"""

from __future__ import annotations

from datetime import date, datetime

from scribe.generation.doc_plan import DocPlan

JUSTIFICATION_FILENAME = "scribe-doc-suite-justification.md"

_CURRENT_STRUCTURE_HEADING = "## Current Structure"
_REVISION_HISTORY_HEADING = "## Revision History"


def _render_current_structure(plan: DocPlan) -> str:
    lines = [
        _CURRENT_STRUCTURE_HEADING,
        "",
        plan.rationale or "_No overall rationale recorded._",
        "",
        "| Section | Page Count | Rationale |",
        "|---|---|---|",
    ]
    for section in plan.sections:
        rationale = (section.rationale or "_no rationale recorded_").replace("|", "/")
        lines.append(f"| {section.title} | {len(section.pages)} | {rationale} |")

    lines += ["", "### Pages and grounding sources", ""]
    for section in plan.sections:
        for page in section.pages:
            sources = ", ".join(f"`{s}`" for s in page.sources) if page.sources else "_none recorded_"
            lines.append(f"- `{page.id}` -- {page.title}. Sources: {sources}")

    return "\n".join(lines)


def _existing_history_body(previous_markdown: str | None) -> str:
    """Pull out just the entries under the previous file's Revision History heading, if any."""
    if not previous_markdown or _REVISION_HISTORY_HEADING not in previous_markdown:
        return ""
    return previous_markdown.split(_REVISION_HISTORY_HEADING, 1)[1].strip()


def render_justification_markdown(
    plan: DocPlan,
    *,
    previous_markdown: str | None = None,
    event_label: str,
    event_detail: str = "",
    today: date | None = None,
) -> str:
    """Build the full justification file: a fresh "Current Structure" plus an appended history entry.

    `event_label`/`event_detail` describe what just happened (e.g. "Initial generation", or
    "Revision requested" with the user's freeform request as the detail) and become one new
    dated line appended to the "Revision History" section; everything already logged there
    (from `previous_markdown`, if given) is preserved above it.
    """
    stamp = (today or datetime.now().astimezone().date()).isoformat()
    entry = f"- **{stamp}** -- {event_label}"
    if event_detail:
        entry += f": {event_detail}"

    history_body = _existing_history_body(previous_markdown)
    history_body = f"{history_body}\n{entry}".strip() if history_body else entry

    return (
        "# S.C.R.I.B.E. Documentation Suite -- Structure Justification\n\n"
        "This file explains *why* the doc suite is shaped the way it is (section/page counts, "
        "and what each page is grounded in), and logs every time that structure was decided or "
        "changed. Meant to be committed to version control alongside `.scribe_plan.json` and "
        "`.scribe_manifest.json`.\n\n"
        f"{_render_current_structure(plan)}\n\n"
        f"{_REVISION_HISTORY_HEADING}\n\n{history_body}\n"
    )
