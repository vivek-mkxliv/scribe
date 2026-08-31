"""Tracks the last successful generation per output directory.

`.scribe_manifest.json` (written alongside the generated docs) records the
repo content hash and mode used for the last successful run. This powers two
things: incremental regeneration (skip the whole pipeline if nothing
changed) and drift-checking (`scribe generate --check`, safe for CI -- no
LLM call, just a hash comparison).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

MANIFEST_FILENAME = ".scribe_manifest.json"


@dataclass(frozen=True)
class Manifest:
    repo_hash: str
    mode: str
    doc_ids: list[str]


def manifest_path(output_dir: Path) -> Path:
    return output_dir / MANIFEST_FILENAME


def load_manifest(output_dir: Path) -> Manifest | None:
    path = manifest_path(output_dir)
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return Manifest(
            repo_hash=payload["repo_hash"], mode=payload["mode"], doc_ids=list(payload["doc_ids"])
        )
    except (json.JSONDecodeError, OSError, KeyError, TypeError):
        return None


def write_manifest(output_dir: Path, repo_hash: str, mode: str, doc_ids: list[str]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    manifest = Manifest(repo_hash=repo_hash, mode=mode, doc_ids=doc_ids)
    manifest_path(output_dir).write_text(json.dumps(asdict(manifest)), encoding="utf-8")


def is_up_to_date(output_dir: Path, repo_hash: str, mode: str) -> bool:
    """True if a manifest exists and matches the given `repo_hash`/`mode` exactly."""
    manifest = load_manifest(output_dir)
    return manifest is not None and manifest.repo_hash == repo_hash and manifest.mode == mode


def existing_doc_files(output_dir: Path, doc_ids: list[str]) -> list[Path]:
    """Which of `doc_ids` already exist as files in `output_dir` (manifest or not)."""
    return [output_dir / doc_id for doc_id in doc_ids if (output_dir / doc_id).exists()]
