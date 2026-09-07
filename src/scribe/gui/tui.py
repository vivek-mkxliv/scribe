"""Textual TUI for S.C.R.I.B.E. (`scribe tui`) -- opt-in, requires the `tui` extra.

Mirrors the same form/preset/live-log/confirmation flow as the browser GUI (`gui/server.py`),
reusing the same framework-agnostic core (`gui/app.py`'s `resolve_form_defaults`/`build_config`)
and the same `project/presets.py` functions -- but talks to `pipeline.run()` directly in a
background worker instead of through HTTP polling, since there's no request/response boundary
to work around here.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from textual import work
from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Footer, Header, Input, RichLog, Select, Static, Switch

from scribe import pipeline
from scribe.constants import AudienceMode
from scribe.gui.app import build_config, resolve_form_defaults
from scribe.pipeline import (
    CostConfirmationRequiredError,
    OverwriteConfirmationRequiredError,
    TokenEstimateConfirmationRequiredError,
)
from scribe.project.presets import delete_preset, load_presets, save_preset

_CONFIRMATION_EXCEPTIONS = (
    TokenEstimateConfirmationRequiredError,
    OverwriteConfirmationRequiredError,
    CostConfirmationRequiredError,
)

_MODE_OPTIONS = [(mode.value, mode.value) for mode in AudienceMode]


class ScribeTuiApp(App[None]):
    """Single-screen Textual app: preset picker, config form, generate button, live log."""

    CSS = """
    Screen { layout: vertical; }
    #body { layout: horizontal; height: 1fr; }
    #left { width: 1fr; padding: 1 2; }
    #right { width: 1fr; padding: 1 2; }
    .row { height: 3; layout: horizontal; }
    .row > * { width: 1fr; margin-right: 1; }
    Input, Select { margin-bottom: 1; }
    #generate { margin-top: 1; }
    #confirmBox { border: solid $warning; padding: 1; margin-top: 1; display: none; }
    #confirmBox.visible { display: block; }
    #log { border: solid $primary; height: 1fr; }
    #statusLine { margin-top: 1; }
    """

    def __init__(self, repo_path: Path) -> None:
        super().__init__()
        self.repo_path = repo_path
        self._pending_form: dict[str, Any] | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="body"):
            with Vertical(id="left"):
                yield Static(f"Repo: {self.repo_path}", id="repoLabel")
                with Horizontal(classes="row"):
                    yield Select([], id="presetSelect", prompt="Load preset")
                    yield Input(placeholder="Save as preset name", id="presetName")
                with Horizontal(classes="row"):
                    yield Button("Save preset", id="savePreset")
                    yield Button("Delete selected", id="deletePreset", variant="error")
                yield Select(_MODE_OPTIONS, id="mode", value=AudienceMode.LEAN_TECHNICAL.value)
                yield Input(placeholder="docs", id="outputDir")
                yield Input(placeholder="Provider (blank = auto-detect)", id="provider")
                yield Input(placeholder="Model (blank = provider default)", id="model")
                yield Input(placeholder="API key (blank = env var)", password=True, id="apiKey")
                with Horizontal(classes="row"):
                    yield Input(placeholder="Max output tokens", id="maxTokens")
                    yield Input(placeholder="Temperature", id="temperature")
                with Horizontal(classes="row"):
                    yield Input(placeholder="Token budget", id="tokenBudget")
                    yield Input(placeholder="Max repair attempts", id="maxRepairAttempts")
                with Horizontal(classes="row"):
                    yield Switch(value=False, id="chunked")
                    yield Static("Force chunked generation")
                with Horizontal(classes="row"):
                    yield Switch(value=True, id="verbose")
                    yield Static("Verbose logging")
                yield Button("Generate", id="generate", variant="primary")
                yield Static("Idle", id="statusLine")
                with Vertical(id="confirmBox"):
                    yield Static("", id="confirmMessage")
                    with Horizontal():
                        yield Button("Proceed", id="confirmYes", variant="primary")
                        yield Button("Cancel", id="confirmNo")
            with Vertical(id="right"):
                yield Static("Log", id="logLabel")
                yield RichLog(id="log", wrap=True, highlight=False)
        yield Footer()

    def on_mount(self) -> None:
        self._refresh_defaults(preset_name=None)
        self._refresh_preset_list()

    def _refresh_defaults(self, preset_name: str | None) -> None:
        defaults = resolve_form_defaults(self.repo_path, preset_name)
        self.query_one("#mode", Select).value = defaults.get("mode") or AudienceMode.LEAN_TECHNICAL.value
        self.query_one("#outputDir", Input).value = str(defaults.get("output_dir") or "docs")
        self.query_one("#provider", Input).value = str(defaults.get("provider") or "")
        self.query_one("#model", Input).value = str(defaults.get("model") or "")
        max_tokens = defaults.get("max_tokens")
        self.query_one("#maxTokens", Input).value = "" if max_tokens is None else str(max_tokens)
        temperature = defaults.get("temperature")
        self.query_one("#temperature", Input).value = "" if temperature is None else str(temperature)
        self.query_one("#tokenBudget", Input).value = str(defaults.get("token_budget") or "")
        self.query_one("#maxRepairAttempts", Input).value = str(defaults.get("max_repair_attempts") or "")
        self.query_one("#chunked", Switch).value = bool(defaults.get("chunked", False))
        # Verbose is intentionally NOT restored from a preset -- see gui/static/index.html's
        # matching note; the log always shows full detail regardless, and it should always
        # default back on for a new session.

    def _refresh_preset_list(self) -> None:
        presets = load_presets(self.repo_path)
        select = self.query_one("#presetSelect", Select)
        select.set_options([(name, name) for name in presets])

    def _current_form(self) -> dict[str, Any]:
        return {
            "mode": self.query_one("#mode", Select).value,
            "provider": self.query_one("#provider", Input).value,
            "model": self.query_one("#model", Input).value,
            "api_key": self.query_one("#apiKey", Input).value,
            "output_dir": self.query_one("#outputDir", Input).value,
            "max_tokens": self.query_one("#maxTokens", Input).value,
            "temperature": self.query_one("#temperature", Input).value,
            "token_budget": self.query_one("#tokenBudget", Input).value,
            "max_repair_attempts": self.query_one("#maxRepairAttempts", Input).value,
            "chunked": self.query_one("#chunked", Switch).value,
        }

    def on_select_changed(self, event: Select.Changed) -> None:
        if event.select.id == "presetSelect" and event.value != Select.BLANK:
            self._refresh_defaults(preset_name=str(event.value))

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "generate":
            self._start_generate(confirmed=False)
        elif event.button.id == "confirmYes":
            self._set_confirm_visible(False)
            if self._pending_form is not None:
                self._start_generate(confirmed=True, form=self._pending_form)
        elif event.button.id == "confirmNo":
            self._set_confirm_visible(False)
            self._pending_form = None
            self.query_one("#statusLine", Static).update("Cancelled.")
        elif event.button.id == "savePreset":
            name = self.query_one("#presetName", Input).value.strip()
            if not name:
                self.query_one("#statusLine", Static).update("Enter a preset name first.")
                return
            save_preset(self.repo_path, name, self._current_form())
            self._refresh_preset_list()
            self.query_one("#statusLine", Static).update(f"Saved preset '{name}'.")
        elif event.button.id == "deletePreset":
            select = self.query_one("#presetSelect", Select)
            if select.value != Select.BLANK:
                delete_preset(self.repo_path, str(select.value))
                self._refresh_preset_list()

    def _set_confirm_visible(self, visible: bool) -> None:
        self.query_one("#confirmBox").set_class(visible, "visible")

    def _start_generate(self, *, confirmed: bool, form: dict[str, Any] | None = None) -> None:
        self.query_one("#generate", Button).disabled = True
        self.query_one("#statusLine", Static).update("Running...")
        self._run_generation(form or self._current_form(), confirmed=confirmed)

    @work(thread=True)
    def _run_generation(self, form: dict[str, Any], *, confirmed: bool) -> None:
        log = self.query_one("#log", RichLog)

        def on_status(message: str) -> None:
            self.call_from_thread(log.write, message)

        try:
            config = build_config(self.repo_path, form, assume_yes=confirmed)
            written = pipeline.run(config, on_status=on_status)
            self.call_from_thread(self._on_generate_done, written=written)
        except _CONFIRMATION_EXCEPTIONS as exc:
            self.call_from_thread(self._on_confirmation_required, form, str(exc))
        except Exception as exc:  # deliberately broad: surface ANY pipeline failure, don't crash
            self.call_from_thread(self._on_generate_error, str(exc))

    def _on_generate_done(self, *, written: list[Path]) -> None:
        self.query_one("#generate", Button).disabled = False
        self.query_one("#statusLine", Static).update(f"Done -- {len(written)} file(s) written.")

    def _on_generate_error(self, message: str) -> None:
        self.query_one("#generate", Button).disabled = False
        self.query_one("#statusLine", Static).update(f"Failed: {message}")

    def _on_confirmation_required(self, form: dict[str, Any], message: str) -> None:
        self.query_one("#generate", Button).disabled = False
        self._pending_form = form
        self.query_one("#confirmMessage", Static).update(message)
        self._set_confirm_visible(True)
        self.query_one("#statusLine", Static).update("Waiting for confirmation...")


def run_tui(repo_path: Path) -> None:
    ScribeTuiApp(repo_path).run()
