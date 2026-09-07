"""Per-repo named presets (`scribe.presets.json`) -- reusable CLI/GUI configurations.

Distinct from `scribe.toml`/`[tool.scribe]` (`config_loader.py`): that file is a single, hand-
authored set of blanket defaults never written by scribe itself. This file holds zero or more
NAMED presets (e.g. "quick-draft", "thorough-audit") a user can pick between, and -- unlike
`scribe.toml` -- is meant to be writable by the GUI. JSON (not TOML) specifically because
`tomllib` (stdlib) is read-only; there's no stdlib TOML writer, and round-tripping hand-formatted
TOML without a third-party writer library is lossy. `json` is stdlib read/write, so presets stay
a zero-extra-dependency feature.

Precedence (highest wins): explicit CLI flag > `--preset NAME` values > `scribe.toml` values >
built-in default. Applying that order is the CLI's job; this module only reads/writes the file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

PRESETS_FILENAME = "scribe.presets.json"

# Superset of config_loader.CONFIG_FIELDS -- presets can additionally pin per-run knobs that
# aren't blanket `scribe.toml` defaults today (max_tokens/temperature), plus which env var to
# pull an API key from. Never the raw API key itself -- see module docstring/security note.
PRESET_FIELDS = (
    "mode",
    "provider",
    "model",
    "output_dir",
    "max_repair_attempts",
    "token_budget",
    "chunked",
    "max_tokens",
    "temperature",
    "api_key_env",
)


class PresetError(RuntimeError):
    """Raised for preset operations that can't proceed (e.g. saving a raw API key)."""


def presets_path(repo_path: Path) -> Path:
    return repo_path / PRESETS_FILENAME


def load_presets(repo_path: Path) -> dict[str, dict[str, Any]]:
    """Return `{name: {field: value}}` from `scribe.presets.json`, or `{}` if absent/corrupt.

    Fail-safe: a missing, empty, or unparseable file is treated as "no presets" rather than an
    error, matching `config_loader.py`'s tolerance for a file that isn't there yet. Unknown
    fields on any preset are dropped (not raised) so a hand-edited file with extra comments-as-
    keys or a newer/older schema doesn't break an older/newer scribe version.
    """
    path = presets_path(repo_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    raw_presets = data.get("presets", {})
    if not isinstance(raw_presets, dict):
        return {}
    return {
        name: {k: v for k, v in fields.items() if k in PRESET_FIELDS}
        for name, fields in raw_presets.items()
        if isinstance(fields, dict)
    }


def load_preset(repo_path: Path, name: str) -> dict[str, Any] | None:
    return load_presets(repo_path).get(name)


def save_preset(repo_path: Path, name: str, values: dict[str, Any]) -> Path:
    """Create/overwrite one named preset, preserving every other preset already in the file.

    Only `PRESET_FIELDS` keys in `values` are stored; anything else is silently dropped (the
    same "ignore what we don't recognize" tolerance as loading, applied symmetrically).
    """
    if values.get("api_key"):
        raise PresetError(
            "Refusing to save a raw 'api_key' into a preset -- this file is meant to be "
            "committed to version control. Use 'api_key_env' (the environment variable name to "
            "read the key from at run time) instead."
        )
    path = presets_path(repo_path)
    existing = load_presets(repo_path)
    existing[name] = {k: v for k, v in values.items() if k in PRESET_FIELDS}
    path.write_text(json.dumps({"presets": existing}, indent=2) + "\n", encoding="utf-8")
    return path


def delete_preset(repo_path: Path, name: str) -> bool:
    """Remove one named preset. Returns whether it existed. No-op (not an error) if absent."""
    existing = load_presets(repo_path)
    if name not in existing:
        return False
    del existing[name]
    path = presets_path(repo_path)
    if existing:
        path.write_text(json.dumps({"presets": existing}, indent=2) + "\n", encoding="utf-8")
    else:
        path.unlink(missing_ok=True)
    return True
