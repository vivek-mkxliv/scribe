"""Optional, user-authored standing instructions that persist across every planning run.

`scribe.org.toml` answers "what facts does the team know that code can't tell you". This file
answers a different question: "what has the team decided/preferred about the doc STRUCTURE that
should keep being honored, run after run, without having to repeat it every time". It's the
"memory" piece for steering the planner (and revisions) long-term -- e.g. "always keep a single
FAQ page", "don't split the CLI section per subcommand, one page is enough". Hand-authored,
freeform markdown/text; never auto-generated or overwritten by scribe.
"""

from __future__ import annotations

from pathlib import Path

NOTES_FILENAME = "scribe.notes.md"


def notes_path(repo_path: Path) -> Path:
    return repo_path / NOTES_FILENAME


def load_scribe_notes(repo_path: Path) -> str:
    """Render `scribe.notes.md` as prompt text, or an explicit "no standing notes" instruction.

    Like `load_org_context`, an explicit "nothing was provided" sentence is returned instead of
    an empty string, so the prompt always has a clear, unambiguous instruction here rather than
    a silent gap.
    """
    path = notes_path(repo_path)
    if not path.exists():
        return (
            f"No standing notes/instructions were provided ({NOTES_FILENAME} not found). "
            "Plan the structure from the repo signals alone."
        )
    try:
        content = path.read_text(encoding="utf-8").strip()
    except OSError:
        return f"{NOTES_FILENAME} exists but couldn't be read -- treat it as unavailable."
    if not content:
        return f"{NOTES_FILENAME} exists but is empty -- treat it as unavailable."
    return (
        "The following standing notes/instructions were explicitly written by the team and "
        "should be honored whenever they conflict with a default heuristic below (but never "
        "used to override a concrete repo signal with a fabricated fact):\n" + content
    )
