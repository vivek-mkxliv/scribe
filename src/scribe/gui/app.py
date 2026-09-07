"""Framework-agnostic logic backing the browser GUI (`gui/server.py`).

Kept separate from the HTTP plumbing so the actual behavior -- resolving form defaults, building
a `ScribeConfig` from submitted values, running the pipeline and tracking its live status -- is
unit-testable without spinning up a real server/socket.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from scribe import pipeline
from scribe.config import DEFAULT_MAX_REPAIR_ATTEMPTS, DEFAULT_TOKEN_BUDGET, ScribeConfig
from scribe.constants import AudienceMode
from scribe.extraction.cache import DEFAULT_CACHE_ROOT
from scribe.pipeline import (
    CostConfirmationRequiredError,
    OverwriteConfirmationRequiredError,
    TokenEstimateConfirmationRequiredError,
)
from scribe.project.config_loader import load_project_config
from scribe.project.presets import load_preset
from scribe.providers.registry import PROVIDER_PRESETS
from scribe.providers.resolution import NoProviderResolvedError, resolve_provider_and_key

_CONFIRMATION_EXCEPTIONS = (
    TokenEstimateConfirmationRequiredError,
    OverwriteConfirmationRequiredError,
    CostConfirmationRequiredError,
)


def _default_model_for(provider: str) -> str | None:
    preset = PROVIDER_PRESETS.get(provider)
    return preset.recommended_models[0] if preset and preset.recommended_models else None


def resolve_form_defaults(repo_path: Path, preset_name: str | None = None) -> dict[str, Any]:
    """Merge built-in defaults <- `scribe.toml` <- a named preset, to pre-fill the GUI form.

    The submitted form is expected to carry the FULLY resolved values back (whether left at
    whatever was pre-filled here, or edited) -- unlike the CLI, there's no separate "was this
    left at its default" tracking needed once the browser has the form.
    """
    defaults: dict[str, Any] = {
        "mode": AudienceMode.LEAN_TECHNICAL.value,
        "provider": "",
        "model": "",
        "output_dir": "docs",
        "max_repair_attempts": DEFAULT_MAX_REPAIR_ATTEMPTS,
        "token_budget": DEFAULT_TOKEN_BUDGET,
        "chunked": False,
        "max_tokens": None,
        "temperature": None,
    }
    defaults.update(load_project_config(repo_path))
    if preset_name:
        preset = load_preset(repo_path, preset_name)
        if preset:
            defaults.update(preset)
    return defaults


def _confirmation_payload(
    exc: TokenEstimateConfirmationRequiredError
    | OverwriteConfirmationRequiredError
    | CostConfirmationRequiredError,
) -> dict[str, Any]:
    """Turn one of the three pipeline confirmation-required exceptions into a JSON-able dict."""
    if isinstance(exc, TokenEstimateConfirmationRequiredError):
        return {
            "type": "token_estimate",
            "message": str(exc),
            "details": {
                "page_token_estimates": exc.page_token_estimates,
                "total_estimated_tokens": exc.total_estimated_tokens,
            },
        }
    if isinstance(exc, OverwriteConfirmationRequiredError):
        return {
            "type": "overwrite",
            "message": str(exc),
            "details": {"existing_files": [str(p) for p in exc.existing_files]},
        }
    return {
        "type": "cost",
        "message": str(exc),
        "details": {"estimated_tokens": exc.estimated_tokens, "token_budget": exc.token_budget},
    }


def build_config(repo_path: Path, form: dict[str, Any], *, assume_yes: bool) -> ScribeConfig:
    """Build a `ScribeConfig` from already-resolved GUI form values (see `resolve_form_defaults`)."""
    mode = AudienceMode(form.get("mode") or AudienceMode.LEAN_TECHNICAL.value)
    resolution = resolve_provider_and_key(form.get("provider") or None, form.get("api_key") or None)
    model = form.get("model") or _default_model_for(resolution.provider)
    if not model:
        raise NoProviderResolvedError(
            f"No default model known for provider {resolution.provider!r}; choose one explicitly."
        )

    output_dir = Path(form.get("output_dir") or "docs")
    resolved_output_dir = output_dir if output_dir.is_absolute() else repo_path / output_dir

    def _optional_number(key: str, cast):
        value = form.get(key)
        return cast(value) if value not in (None, "") else None

    return ScribeConfig(
        repo_path=repo_path,
        output_dir=resolved_output_dir,
        mode=mode,
        provider=resolution.provider,
        model=model,
        api_key=resolution.api_key,
        max_repair_attempts=int(form.get("max_repair_attempts") or DEFAULT_MAX_REPAIR_ATTEMPTS),
        token_budget=int(form.get("token_budget") or DEFAULT_TOKEN_BUDGET),
        cache_dir=DEFAULT_CACHE_ROOT,
        chunked=bool(form.get("chunked", False)),
        assume_yes=assume_yes,
        temperature=_optional_number("temperature", float),
        max_tokens=_optional_number("max_tokens", int),
    )


@dataclass
class RunState:
    """Thread-safe status of the one in-flight (or most recently completed) generation run.

    A single shared run at a time is a deliberate simplification -- this GUI is a single-local-
    user tool, not a multi-tenant service, so there's no need for a run-id per request.
    """

    _lock: threading.Lock = field(default_factory=threading.Lock)
    messages: list[str] = field(default_factory=list)
    running: bool = False
    done: bool = False
    error: str | None = None
    confirmation: dict[str, Any] | None = None
    written: list[str] = field(default_factory=list)

    def mark_starting(self) -> None:
        """Synchronously flag a run as in-progress, before the actual work is handed to a
        background thread -- closes the race where a second `POST /api/generate` could slip in
        between "thread started" and that thread's own first `reset()` call."""
        with self._lock:
            self.running = True

    def reset(self) -> None:
        with self._lock:
            self.messages = []
            self.running = True
            self.done = False
            self.error = None
            self.confirmation = None
            self.written = []

    def add_message(self, message: str) -> None:
        with self._lock:
            self.messages.append(message)

    def finish(
        self,
        *,
        written: list[str] | None = None,
        error: str | None = None,
        confirmation: dict[str, Any] | None = None,
    ) -> None:
        with self._lock:
            self.running = False
            self.done = True
            self.written = written or []
            self.error = error
            self.confirmation = confirmation

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "messages": list(self.messages),
                "running": self.running,
                "done": self.done,
                "error": self.error,
                "confirmation": self.confirmation,
                "written": list(self.written),
            }


def run_generation(repo_path: Path, form: dict[str, Any], state: RunState, *, confirmed: bool) -> None:
    """Run `pipeline.run()` to completion, updating `state` as it goes.

    Meant to be called on a background thread by the HTTP handler so the request that triggers
    it can return immediately; the browser polls `state.snapshot()` (via `GET /api/status`) for
    progress instead of holding one long-lived request open.
    """
    state.reset()
    try:
        config = build_config(repo_path, form, assume_yes=confirmed)
        written = pipeline.run(config, on_status=state.add_message)
        state.finish(written=[str(p) for p in written])
    except _CONFIRMATION_EXCEPTIONS as exc:
        state.finish(confirmation=_confirmation_payload(exc))
    except Exception as exc:  # deliberately broad: surface ANY pipeline failure to the GUI
        state.finish(error=str(exc))
