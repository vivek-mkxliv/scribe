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


def build_repair_followup(issue_description: str) -> str:
    """Build a short follow-up message asking the LLM to fix a validation failure."""
    return REPAIR_FOLLOWUP_TEMPLATE.format(issue_description=issue_description)
