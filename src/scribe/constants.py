"""Audience modes and their corresponding output document suites."""

from enum import Enum


class AudienceMode(str, Enum):
    """The two supported documentation generation modes."""

    LEAN_TECHNICAL = "lean_technical"
    OPERATOR_SPLIT = "operator_split"


# Fixed, per-mode doc lists. No longer the primary source of a run's document structure --
# see `generation/doc_plan.py`, which derives a repo-specific structure (sections of pages,
# sized to what's actually in the repo, not a round number) via an LLM planning call. These
# lists now serve only as the deterministic, zero-cost fallback (`doc_plan.heuristic_doc_plan`)
# used for `--dry-run` (which must never make a real LLM call) and when plan derivation fails.
DOC_SUITE: dict[AudienceMode, list[str]] = {
    AudienceMode.LEAN_TECHNICAL: [
        "README.md",
        "USER_MANUAL.md",
        "TROUBLESHOOTING.md",
        "DEV_PLAYBOOK.md",
    ],
    AudienceMode.OPERATOR_SPLIT: [
        "HOME.md",
        "DOCS_HOME.md",
        "USER_GUIDES.md",
        "TROUBLESHOOTING.md",
        "FAQS.md",
        "CONTACT_US.md",
        "USER_DOCS_TECHNICAL.md",
        "DEV_DOCS.md",
    ],
}

# Tone/audience guidance handed to both the planning prompt (deciding the structure) and the
# generation prompt (writing the content) -- kept separate from the doc list itself since the
# actual sections/pages are now derived per-repo, not fixed.
AUDIENCE_MODE_GUIDANCE: dict[AudienceMode, str] = {
    AudienceMode.LEAN_TECHNICAL: (
        "A small internal engineering team (a scrum master + 2 engineers). One direct, technical "
        "tone throughout. Always include an executive-summary/quick-start section and a "
        "developer/architecture section; add more sections or pages only if the repo's real "
        "structure (multiple subsystems, multiple entry points, a large surface area) warrants it."
    ),
    AudienceMode.OPERATOR_SPLIT: (
        "Two distinct audiences sharing one documentation space: operators (strictly "
        "transactional, jargon-free, step-by-step, no architecture) and engineers (technical, "
        "architecture-level). Always include a documentation-home/routing section pointing each "
        "audience at their part, an operator-facing execution/troubleshooting side, and an "
        "engineer-facing architecture/technical side. Add more sections or pages only where the "
        "repo's real shape (distinct workflows, distinct subsystems) justifies a separate page."
    ),
}

# Named-section markers the LLM is instructed to wrap each document in.
# Robust to stray `---` horizontal rules inside generated content, unlike a
# positional divider split.
DOC_BEGIN_MARKER = '<!-- SCRIBE:BEGIN doc="{doc_id}" -->'
DOC_END_MARKER = "<!-- SCRIBE:END -->"
