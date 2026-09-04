"""Tracks the last successful generation per output directory.

`.scribe_manifest.json` (written alongside the generated docs) records the repo content hash
and mode used for the last successful run. This powers three things: incremental regeneration
(skip the whole pipeline if nothing changed), drift-checking (`scribe generate --check`, safe
for CI -- no LLM call, just a hash comparison), and per-page content staleness (`page_hashes`:
a hash of the specific source files each page said it's grounded in, so a change to one part of
the repo doesn't force every page to regenerate -- see `pipeline._resolve_stale_pages`).

Both `.scribe_manifest.json` and `.scribe_plan.json` (written by `generation/doc_plan.py`) are
meant to be committed alongside the generated docs, not gitignored -- they're what lets a
teammate (or CI, on a different machine with an empty `~/.scribe_cache`) regenerate the same
structure and skip unchanged pages, instead of every clone re-deriving its own plan from scratch.
So is `scribe-doc-suite-justification.md` (`generation/justification.py`) -- the human-readable
explanation of *why* the structure looks the way it does, plus a dated log of every time it was
(re)derived or revised.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path

MANIFEST_FILENAME = ".scribe_manifest.json"


@dataclass(frozen=True)
class Manifest:
    repo_hash: str
    mode: str
    doc_ids: list[str]
    page_hashes: dict[str, str] = field(default_factory=dict)


def manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_FILENAME


def load_manifest(output_dir: Path) -> Manifest | None:
    path = manifest_path(output_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Manifest(
            repo_hash=payload["repo_hash"],
            mode=payload["mode"],
            doc_ids=list(payload["doc_ids"]),
            page_hashes=dict(payload.get("page_hashes", {})),
        )
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def write_manifest(
    output_dir: Path,
    repo_hash: str,
    mode: str,
    doc_ids: list[str],
    page_hashes: dict[str, str] | None = None,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(repo_hash=repo_hash, mode=mode, doc_ids=doc_ids, page_hashes=page_hashes or {})
    manifest_path(output_dir).write_text(json.dumps(asdict(manifest)), encoding="utf-8")


def is_up_to_date(output_dir: Path, repo_hash: str, mode: str) -> bool:
    """True if a manifest exists and matches the given `repo_hash`/`mode` exactly."""
    manifest = load_manifest(output_dir)
    return manifest is not None and manifest.repo_hash == repo_hash and manifest.mode == mode


def existing_doc_files(output_dir: Path, doc_ids: list[str]) -> list[Path]:
    """Which of `doc_ids` already exist as files in `output_dir` (manifest or not)."""
    return [output_dir / doc_id for doc_id in doc_ids if (output_dir / doc_id).exists()]
