"""Shared rules for what counts as "noise" when scanning an arbitrary target repo.

Used by both `extractor.py` (native fallback + project tree) and `cache.py`
(content-hash walk for non-git repos), so there is exactly one skip-list and
one symlink-safe walking strategy, instead of two that can silently drift
apart. Covers common VCS/build/dependency/IDE directories across the
ecosystems this tool is likely to be pointed at, including game-engine
projects (Unreal/Unity) that are common in ADAS/simulation tooling and are
frequently NOT git repos (Perforce), where the git-based fast path below
doesn't apply and this walker is what actually runs.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

SKIP_DIR_NAMES = frozenset(
    {
        # VCS / tool caches
        ".git",
        ".hg",
        ".svn",
        ".scribe_cache",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".idea",
        ".vs",
        # Python / JS dependency & build output
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        "dist",
        "build",
        ".eggs",
        # .NET / Rust build output
        "bin",
        "obj",
        "target",
        # Unreal Engine build/derived artifacts -- large binary trees, not source
        "Binaries",
        "Intermediate",
        "Saved",
        "DerivedDataCache",
        # Unity build/derived artifacts
        "Library",
        "Temp",
        "Logs",
        # Previously-generated docs (don't feed prior scribe output back in as "source")
        "docs",
    }
)


def iter_repo_files(repo_path: Path, skip_dirs: frozenset[str] = SKIP_DIR_NAMES) -> Iterator[Path]:
    """Yield every file under `repo_path`, pruning noise directories up front.

    Uses `os.walk(..., followlinks=False)` rather than `Path.rglob`, which
    means: (a) skipped directories (e.g. `node_modules`, Unreal's
    `Intermediate/`) are never even descended into, not just filtered out
    after the fact, and (b) symlinked directories are never followed, which
    avoids infinite loops on circular symlinks -- a real risk when this tool
    is pointed at a repo it doesn't control.
    """
    for dirpath, dirnames, filenames in os.walk(repo_path, followlinks=False):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for filename in filenames:
            file_path = Path(dirpath) / filename
            if file_path.is_symlink():
                continue
            yield file_path
