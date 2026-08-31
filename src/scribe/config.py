"""Runtime configuration for a single S.C.R.I.B.E. generation run."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from scribe.constants import AudienceMode
from scribe.extraction.cache import DEFAULT_CACHE_ROOT

DEFAULT_MAX_REPAIR_ATTEMPTS = 2
DEFAULT_TOKEN_BUDGET = 150_000


@dataclass(frozen=True)
class ScribeConfig:
    """Immutable configuration resolved from CLI arguments/environment."""

    repo_path: Path
    output_dir: Path
    mode: AudienceMode
    provider: str
    model: str
    api_key: str | None
    base_url: str | None = None
    dry_run: bool = False
    use_cache: bool = True
    refresh_cache: bool = False
    force_native_extractor: bool = False
    max_repair_attempts: int = DEFAULT_MAX_REPAIR_ATTEMPTS
    token_budget: int = DEFAULT_TOKEN_BUDGET
    # User-level by default so pointing this at a repo you don't own never
    # leaves a `.scribe_cache/` directory behind inside it.
    cache_dir: Path = field(default_factory=lambda: DEFAULT_CACHE_ROOT)
    chunked: bool = False
    assume_yes: bool = False
    temperature: float | None = None
    max_tokens: int | None = None
    incremental: bool = True
    # Path to a user-authored documentation-structure plan (JSON) to compare/use instead of --
    # or alongside -- the repo-derived one. See `generation/doc_plan.py`.
    doc_plan_file: Path | None = None
    # Skip the cached documentation-structure plan and re-derive it via the LLM even if the
    # repo's content hash hasn't changed.
    refresh_plan: bool = False
