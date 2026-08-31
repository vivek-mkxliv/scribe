"""Assembles the final LLM prompt from the master template and run-time context."""

from __future__ import annotations

from importlib import resources

from scribe.constants import AUDIENCE_MODE_GUIDANCE, AudienceMode
from scribe.extraction.models import GraphContext
from scribe.generation.doc_plan import DocPlan

REPAIR_FOLLOWUP_TEMPLATE = (
    "Your previous response did not match the required output contract: {issue_description}. "
    "Resend the FULL response again, including every document, each wrapped in its exact "
    '`<!-- SCRIBE:BEGIN doc="..." -->` / `<!-- SCRIBE:END -->` marker pair as originally instructed. '
    "Pay special attention to the document ids you got wrong."
)


def _load_template(name: str) -> str:
    template_path = resources.files("scribe.templates").joinpath(name)
    return template_path.read_text(encoding="utf-8")


def _render(project_context: str, graphifyy_context_text: str, doc_plan: DocPlan) -> str:
    """Fill the master template. The one place that actually calls `.format()`."""
    return _load_template("master_prompt.md").format(
        project_context=project_context,
        graphifyy_context=graphifyy_context_text,
        audience_mode=doc_plan.mode.value,
        audience_guidance=AUDIENCE_MODE_GUIDANCE[doc_plan.mode],
        doc_plan=doc_plan.to_prompt_text(),
    )


def build_prompt(
    project_context: str,
    graph_context: GraphContext,
    doc_plan: DocPlan,
    *,
    max_graph_modules: int | None = None,
) -> str:
    """Fill the master template with the extracted context and the finalized doc plan."""
    return _render(project_context, graph_context.to_prompt_text(max_modules=max_graph_modules), doc_plan)


def build_prompt_with_digest_text(project_context: str, digest_text: str, doc_plan: DocPlan) -> str:
    """Fill the master template with a pre-rendered digest instead of a `GraphContext`.

    Used by the chunked/map-reduce path (`generation/chunking.py`), where the "digest" is a
    synthesis of per-package summaries rather than `GraphContext.to_prompt_text()`.
    """
    return _render(project_context, digest_text, doc_plan)


def build_planning_prompt(project_context: str, graph_context: GraphContext, mode: AudienceMode) -> str:
    """Fill the documentation-structure planning template (see `generation/doc_plan.py`)."""
    return _load_template("planning_prompt.md").format(
        project_context=project_context,
        graphifyy_context=graph_context.to_prompt_text(),
        audience_mode=mode.value,
        audience_guidance=AUDIENCE_MODE_GUIDANCE[mode],
    )


def build_repair_followup(issue_description: str) -> str:
    """Build a short follow-up message asking the LLM to fix a validation failure."""
    return REPAIR_FOLLOWUP_TEMPLATE.format(issue_description=issue_description)
