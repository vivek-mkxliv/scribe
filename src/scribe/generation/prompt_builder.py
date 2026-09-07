"""Assembles the final LLM prompt from the master template and run-time context."""

from __future__ import annotations

from importlib import resources

from scribe.constants import AUDIENCE_MODE_GUIDANCE, AudienceMode
from scribe.extraction.models import GraphContext
from scribe.generation.doc_plan import DocPage, DocPlan

REPAIR_FOLLOWUP_TEMPLATE = (
    "Your previous response did not match the required output contract: {issue_description}. "
    "Resend the FULL response again, including every document, each wrapped in its exact "
    '`<!-- SCRIBE:BEGIN doc="..." -->` / `<!-- SCRIBE:END -->` marker pair as originally instructed. '
    "Pay special attention to the document ids you got wrong."
)

# Appended when a single-page call's marker id doesn't match its assignment -- observed in
# practice: the model mislabels its output with a SIBLING page's id from the "Full
# Documentation Plan" cross-linking list (often the previous page generated) instead of the
# one actually assigned to it.
REPAIR_FOLLOWUP_WRONG_ID_HINT = (
    ' The EXACT doc id for THIS page is "{expected_doc_id}" -- use exactly that string in the '
    "marker, character-for-character. Do not reuse a different id from the Full Documentation "
    "Plan list (e.g. a sibling page, or the one you wrote in a previous call) even if it looks "
    "similar or appeared first in that list."
)


def _load_template(name: str) -> str:
    template_path = resources.files("scribe.templates").joinpath(name)
    return template_path.read_text(encoding="utf-8")


def _render_target_page(page: DocPage) -> str:
    return f'(doc="{page.id}") {page.title}: {page.description}'.rstrip(": ")


def build_page_prompt(
    project_context: str,
    digest_text: str,
    doc_plan: DocPlan,
    target_page: DocPage,
    *,
    cli_surface_text: str = "",
    org_context_text: str = "",
) -> str:
    """Fill the per-page template: write exactly `target_page` now.

    The full `doc_plan` is still shown (for cross-link awareness of sibling pages), but the
    output contract is scoped to this one page -- one LLM call produces one document, so each
    page gets its own full `--max-tokens` budget instead of splitting one budget N ways.
    """
    return _load_template("master_prompt.md").format(
        project_context=project_context,
        graphifyy_context=digest_text,
        audience_mode=doc_plan.mode.value,
        audience_guidance=AUDIENCE_MODE_GUIDANCE[doc_plan.mode],
        doc_plan=doc_plan.to_prompt_text(),
        target_page=_render_target_page(target_page),
        cli_surface=cli_surface_text,
        org_context=org_context_text,
    )


def build_planning_prompt(
    project_context: str,
    graph_context: GraphContext,
    mode: AudienceMode,
    cli_surface_text: str = "",
    user_notes_text: str = "",
) -> str:
    """Fill the documentation-structure planning template (see `generation/doc_plan.py`)."""
    return _load_template("planning_prompt.md").format(
        project_context=project_context,
        graphifyy_context=graph_context.to_prompt_text(),
        audience_mode=mode.value,
        audience_guidance=AUDIENCE_MODE_GUIDANCE[mode],
        cli_surface=cli_surface_text,
        user_notes=user_notes_text,
    )


def build_revision_prompt(
    project_context: str,
    graph_context: GraphContext,
    mode: AudienceMode,
    current_plan: DocPlan,
    current_justification: str,
    revision_request: str,
    cli_surface_text: str = "",
) -> str:
    """Fill the documentation-structure revision template (see `generation/doc_plan.py`)."""
    return _load_template("revision_prompt.md").format(
        project_context=project_context,
        graphifyy_context=graph_context.to_prompt_text(),
        audience_mode=mode.value,
        audience_guidance=AUDIENCE_MODE_GUIDANCE[mode],
        cli_surface=cli_surface_text,
        current_plan_json=current_plan.to_json(),
        current_justification=current_justification or "_No justification doc found._",
        revision_request=revision_request,
    )


def build_repair_followup(issue_description: str, *, expected_doc_id: str | None = None) -> str:
    """Build a short follow-up message asking the LLM to fix a validation failure.

    `expected_doc_id`, if given (single-page generation calls only), appends an explicit
    restatement of the one correct id -- see `REPAIR_FOLLOWUP_WRONG_ID_HINT`.
    """
    message = REPAIR_FOLLOWUP_TEMPLATE.format(issue_description=issue_description)
    if expected_doc_id is not None:
        message += REPAIR_FOLLOWUP_WRONG_ID_HINT.format(expected_doc_id=expected_doc_id)
    return message
