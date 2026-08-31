"""Shared git helpers used by both the extraction cache and the native extractor."""

from __future__ import annotations

import subprocess
from pathlib import Path


def list_tracked_files(repo_path: Path) -> list[str] | None:
    """Return `git ls-files` output for `repo_path`, or None if not a git checkout."""
    try:
        result = subprocess.run(
            ["git", "-C", str(repo_path), "ls-files"],
            capture_output=True,
            text=True,
            check=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    return [line for line in result.stdout.splitlines() if line]
