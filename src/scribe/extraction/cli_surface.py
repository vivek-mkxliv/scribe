"""Best-effort, regex-based detection of a repo's real CLI surface (subcommands/flags).

`GraphContext` (from Graphifyy or the native fallback) only captures module-level
dependency edges -- it has no notion of CLI arguments, subcommands, or flags. Left
ungrounded, an LLM asked to document "how to use the CLI" will confidently invent a
plausible-looking interface instead of describing the real one. Observed in practice
against a real repo: a fabricated single `run` command with `--config`/`--example`
flags, when the real CLI had three subcommands (argparse sub-parsers) and a dozen real
flags. This module is deliberately conservative -- not a real parser for any of these
frameworks, just enough pattern-matching to give the prompt REAL facts to cite instead
of letting the model guess.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from scribe.extraction.scan_config import iter_repo_files

# Filenames likely to contain the actual CLI entry point, checked by substring so
# `jira_creator/cli.py` and `myapp/cli.py` both match.
_ENTRY_POINT_HINTS = ("cli.py", "__main__.py", "main.py", "cmd.py", "commands.py")
_MAX_FILES_SCANNED = 20

_ARGPARSE_SUBPARSER = re.compile(r'add_parser\(\s*["\'](?P<name>[\w-]+)["\']')
_ARGPARSE_FLAG = re.compile(r'add_argument\(\s*["\'](?P<flag>--[\w-]+)["\']')
_CLICK_COMMAND = re.compile(r'@\w+\.command\(\s*["\']?(?P<name>[\w-]*)')
_CLICK_OPTION = re.compile(r'@\w+\.option\(\s*["\'](?P<flag>--[\w-]+)["\']')


@dataclass
class CliSurface:
    """Real CLI facts detected in one source file -- never invented."""

    source_file: str
    subcommands: list[str] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)


def detect_cli_surface(repo_path: Path, max_files: int = _MAX_FILES_SCANNED) -> list[CliSurface]:
    """Scan likely entry-point files for argparse/click subcommands and flags.

    Returns one `CliSurface` per file where something was actually found. An empty
    list means nothing was detected -- callers should tell the model that explicitly
    rather than staying silent, so it doesn't fill the gap with invented flags.
    """
    surfaces: list[CliSurface] = []
    checked = 0
    for file_path in iter_repo_files(repo_path):
        if file_path.suffix != ".py":
            continue
        if not any(hint in file_path.name.lower() for hint in _ENTRY_POINT_HINTS):
            continue
        if checked >= max_files:
            break
        checked += 1

        try:
            text = file_path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue

        subcommands = list(
            dict.fromkeys(
                [m.group("name") for m in _ARGPARSE_SUBPARSER.finditer(text)]
                + [m.group("name") for m in _CLICK_COMMAND.finditer(text) if m.group("name")]
            )
        )
        flags = sorted(
            {m.group("flag") for m in _ARGPARSE_FLAG.finditer(text)}
            | {m.group("flag") for m in _CLICK_OPTION.finditer(text)}
        )

        if not subcommands and not flags:
            continue
        surfaces.append(
            CliSurface(
                source_file=file_path.relative_to(repo_path).as_posix(), subcommands=subcommands, flags=flags
            )
        )

    return surfaces


_NO_SURFACE_DETECTED_TEXT = (
    "No CLI subcommands/flags were reliably detected by static analysis of this repo. "
    "Do NOT invent specific command names or flags -- describe any CLI usage only in "
    "terms of what's actually shown in the project context/knowledge graph above, or "
    "state plainly that the exact interface isn't available from static analysis."
)


def render_cli_surface_text(surfaces: list[CliSurface]) -> str:
    """Render detected CLI facts for prompt injection, or an explicit "nothing found"
    instruction so the model doesn't fabricate an interface to fill the silence."""
    if not surfaces:
        return _NO_SURFACE_DETECTED_TEXT

    lines = [
        "Detected CLI surface (from static analysis of the real source -- these are the "
        "ONLY subcommands/flags that actually exist; do not invent additional ones):"
    ]
    for surface in surfaces:
        lines.append(f"- {surface.source_file}:")
        if surface.subcommands:
            lines.append(f"  subcommands: {', '.join(surface.subcommands)}")
        if surface.flags:
            lines.append(f"  flags seen in this file: {', '.join(surface.flags)}")
    return "\n".join(lines)


def build_cli_surface_text(repo_path: Path) -> str:
    """Convenience wrapper: detect then render in one call."""
    return render_cli_surface_text(detect_cli_surface(repo_path))
