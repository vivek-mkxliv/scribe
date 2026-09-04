"""Tests for `generation/justification.py` -- the human-readable structure-justification doc."""

from __future__ import annotations

from datetime import date

from scribe.constants import AudienceMode
from scribe.generation.doc_plan import DocPage, DocPlan, DocSection
from scribe.generation.justification import render_justification_markdown

PLAN = DocPlan(
    mode=AudienceMode.LEAN_TECHNICAL,
    rationale="Two workflows detected: CLI and GUI.",
    sections=[
        DocSection(
            id="cli",
            title="CLI",
            description="Command-line usage",
            rationale="3 subcommands detected -> 3 pages.",
            pages=[
                DocPage(id="cli/01-run.md", title="Run", sources=["cli/run.py"]),
                DocPage(id="cli/02-init.md", title="Init", sources=["cli/init.py"]),
            ],
        ),
        DocSection(id="gui", title="GUI", pages=[DocPage(id="gui/01-overview.md", title="Overview")]),
    ],
)


def test_render_includes_overall_and_per_section_rationale():
    markdown = render_justification_markdown(PLAN, event_label="Initial generation")

    assert "Two workflows detected" in markdown
    assert "3 subcommands detected" in markdown
    assert "_no rationale recorded_" in markdown  # the GUI section has none


def test_render_lists_pages_with_their_sources():
    markdown = render_justification_markdown(PLAN, event_label="Initial generation")

    assert "cli/01-run.md" in markdown
    assert "`cli/run.py`" in markdown
    assert "_none recorded_" in markdown  # gui/01-overview.md has no sources


def test_render_appends_dated_entry_to_revision_history():
    markdown = render_justification_markdown(PLAN, event_label="Initial generation", today=date(2026, 1, 1))

    assert "## Revision History" in markdown
    assert "**2026-01-01** -- Initial generation" in markdown


def test_render_preserves_prior_history_and_appends_new_entry():
    first = render_justification_markdown(PLAN, event_label="Initial generation", today=date(2026, 1, 1))

    second = render_justification_markdown(
        PLAN,
        previous_markdown=first,
        event_label="Revision requested",
        event_detail="add a security section",
        today=date(2026, 2, 1),
    )

    assert "**2026-01-01** -- Initial generation" in second
    assert "**2026-02-01** -- Revision requested: add a security section" in second


def test_render_current_structure_reflects_only_the_latest_plan():
    first = render_justification_markdown(PLAN, event_label="Initial generation", today=date(2026, 1, 1))

    revised_plan = DocPlan(
        mode=AudienceMode.LEAN_TECHNICAL,
        rationale="Added a security section per request.",
        sections=[*PLAN.sections, DocSection(id="security", title="Security", pages=[])],
    )
    second = render_justification_markdown(
        revised_plan, previous_markdown=first, event_label="Revision requested", today=date(2026, 2, 1)
    )

    assert "Added a security section per request." in second
    assert "Two workflows detected" not in second  # old overall rationale is gone from "Current Structure"
