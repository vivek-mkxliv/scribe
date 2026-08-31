"""Content-hash based caching for extraction results.

Avoids re-running Graphifyy (or the native fallback) when nothing in the
repo has changed since the last `scribe generate`. Cached by default under a
user-level directory (`~/.scribe_cache/<repo-key>/`), keyed by a hash of the
target repo's absolute path -- not inside the target repo itself, since this
tool is meant to be pointed at repos it doesn't own (no surprise
`.scribe_cache/` directory left behind in someone else's checkout).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from pathlib import Path

from scribe.extraction.gitutil import list_tracked_files
from scribe.extraction.models import DependencyEdge, GraphContext, GraphStats, ModuleNode
from scribe.extraction.scan_config import iter_repo_files

DEFAULT_CACHE_ROOT = Path.home() / ".scribe_cache"


def _cache_dir_for_repo(repo_path: Path, cache_root: Path) -> Path:
    """A per-repo subfolder of `cache_root`, keyed by the repo's absolute path.

    Keying by path (not just content hash) means two different repos can
    never collide in a shared, user-level cache root.
    """
    repo_key = hashlib.sha256(str(repo_path.resolve()).encode("utf-8")).hexdigest()[:16]
    return cache_root / repo_key


def compute_repo_hash(repo_path: Path) -> str:
    """Hash tracked (or, absent git, all non-ignored-looking) file identities.

    Uses `git ls-files` + per-file (path, size, mtime) when the repo is a git
    checkout, since that's fast and respects `.gitignore` for free. Falls
    back to a noise-pruned, symlink-safe tree walk when git isn't available
    (e.g. Perforce-based game-engine projects, common in ADAS/Unreal tooling).
    """
    entries: list[str] = []
    tracked = list_tracked_files(repo_path)
    if tracked is not None:
        for rel_path in tracked:
            full_path = repo_path / rel_path
            try:
                stat = full_path.stat()
            except OSError:
                continue
            entries.append(f"{rel_path}:{stat.st_size}:{stat.st_mtime_ns}")
    else:
        for path in sorted(iter_repo_files(repo_path)):
            rel_path = path.relative_to(repo_path).as_posix()
            try:
                stat = path.stat()
            except OSError:
                continue
            entries.append(f"{rel_path}:{stat.st_size}:{stat.st_mtime_ns}")

    digest = hashlib.sha256("\n".join(entries).encode("utf-8")).hexdigest()
    return digest


def load_cached_context(
    repo_path: Path, repo_hash: str, cache_root: Path = DEFAULT_CACHE_ROOT
) -> GraphContext | None:
    cache_file = _cache_dir_for_repo(repo_path, cache_root) / f"{repo_hash}.json"
    if not cache_file.exists():
        return None
    try:
        payload = json.loads(cache_file.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None

    try:
        return GraphContext(
            modules=[ModuleNode(**m) for m in payload["modules"]],
            edges=[DependencyEdge(**e) for e in payload["edges"]],
            entry_points=payload["entry_points"],
            stats=GraphStats(**payload["stats"]),
            source="cache",
        )
    except (KeyError, TypeError):
        return None


def store_cached_context(
    repo_path: Path, repo_hash: str, context: GraphContext, cache_root: Path = DEFAULT_CACHE_ROOT
) -> None:
    cache_dir = _cache_dir_for_repo(repo_path, cache_root)
    cache_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "modules": [asdict(m) for m in context.modules],
        "edges": [asdict(e) for e in context.edges],
        "entry_points": context.entry_points,
        "stats": asdict(context.stats),
    }
    (cache_dir / f"{repo_hash}.json").write_text(json.dumps(payload), encoding="utf-8")
