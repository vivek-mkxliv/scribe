"""Regenerates the provider tables in MODELS.md from `scribe.providers.registry`.

`registry.py` is the single source of truth for provider metadata; this
script is the one place that turns it into human-readable Markdown, so the
two can never silently drift apart. Run it after editing `registry.py`:

    python scripts/generate_models_doc.py            # rewrite MODELS.md
    python scripts/generate_models_doc.py --check     # exit 1 if MODELS.md is stale (CI-friendly)
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "src"))

from scribe.providers.registry import PROVIDER_PRESETS  # noqa: E402 -- must follow sys.path.insert above

MODELS_MD_PATH = REPO_ROOT / "MODELS.md"
START_MARKER = (
    "<!-- AUTO-GENERATED:PROVIDERS:START (run `python scripts/generate_models_doc.py` to refresh) -->"
)
END_MARKER = "<!-- AUTO-GENERATED:PROVIDERS:END -->"


def _table(headers: list[str], rows: list[list[str]]) -> str:
    lines = [f"| {' | '.join(headers)} |", f"|{'|'.join('---' for _ in headers)}|"]
    lines += [f"| {' | '.join(row)} |" for row in rows]
    return "\n".join(lines)


def render_provider_tables() -> str:
    paid_rows = []
    free_rows = []
    for preset in PROVIDER_PRESETS.values():
        models = ", ".join(f"`{m}`" for m in preset.recommended_models)
        row = [f"`{preset.name}`", models, preset.notes]
        if preset.cost == "paid":
            paid_rows.append(row)
        else:
            free_rows.append([f"`{preset.name}`", models, preset.cost, preset.notes])

    sections = [
        "## Recommended (Paid, Best Quality)",
        "",
        _table(["Provider", "Recommended Models", "Why"], paid_rows),
        "",
        "## Free / Open-Source / Local",
        "",
        _table(["Provider", "Recommended Models", "Cost", "Notes"], free_rows),
    ]
    return "\n".join(sections)


def regenerate(check_only: bool = False) -> bool:
    """Rewrite (or, in check mode, just compare) MODELS.md. Returns True if unchanged."""
    original = MODELS_MD_PATH.read_text(encoding="utf-8")
    start_index = original.index(START_MARKER) + len(START_MARKER)
    end_index = original.index(END_MARKER)

    updated = f"{original[:start_index]}\n\n{render_provider_tables()}\n\n{original[end_index:]}"
    unchanged = updated == original

    if not check_only and not unchanged:
        MODELS_MD_PATH.write_text(updated, encoding="utf-8")

    return unchanged


if __name__ == "__main__":
    is_check = "--check" in sys.argv
    was_unchanged = regenerate(check_only=is_check)
    if is_check and not was_unchanged:
        print("MODELS.md is stale relative to scribe.providers.registry. Run without --check to refresh.")
        sys.exit(1)
    print("MODELS.md is up to date." if was_unchanged else "MODELS.md regenerated.")
