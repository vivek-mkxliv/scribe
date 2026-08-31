"""Loads project-level defaults from `[tool.scribe]` in `pyproject.toml`, or `scribe.toml`.

Precedence (highest wins): explicit CLI flag > config file value > built-in default.
The CLI is responsible for applying that precedence; this module only reads the file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

CONFIG_FIELDS = (
    "mode",
    "provider",
    "model",
    "output_dir",
    "max_repair_attempts",
    "token_budget",
    "chunked",
)


def load_project_config(repo_path: Path) -> dict[str, Any]:
    """Return `{field: value}` from `scribe.toml` or `pyproject.toml`'s `[tool.scribe]`.

    `scribe.toml` (if present) takes precedence over `pyproject.toml`, matching the
    convention that a dedicated config file is more specific than a shared one.
    Unknown keys are ignored rather than raising, so the file can carry other
    tool-specific comments/sections without breaking S.C.R.I.B.E.
    """
    scribe_toml = repo_path / "scribe.toml"
    if scribe_toml.exists():
        data = tomllib.loads(scribe_toml.read_text(encoding="utf-8"))
        return {k: v for k, v in data.items() if k in CONFIG_FIELDS}

    pyproject = repo_path / "pyproject.toml"
    if pyproject.exists():
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        tool_section = data.get("tool", {}).get("scribe", {})
        return {k: v for k, v in tool_section.items() if k in CONFIG_FIELDS}

    return {}
