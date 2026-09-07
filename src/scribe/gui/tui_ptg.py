"""Prototype: pytermgui-based TUI, for direct side-by-side comparison against the Textual
version (`gui/tui.py`). NOT wired into the `scribe tui` CLI command -- evaluation only, so
this doesn't force a decision before you've seen both. Run directly:

    python -m scribe.gui.tui_ptg --repo /path/to/repo

IMPORTANT (verified from the project's own docs, not a guess): PyTermGUI's README states the
project "has reached its final release and is no longer under active development" -- archived,
frozen at v7.8.0. It works today (confirmed by actually running/introspecting it while writing
this), but unlike Textual (actively maintained, and already proven working in `gui/tui.py`),
it will not receive future bug fixes or terminal-compatibility updates. Worth weighing.

API notes discovered by introspecting the installed library (not assumed from docs alone):
`Toggle` always renders `states[0]` right after construction regardless of any "checked"
argument -- so to default a toggle to its "on" label, put that label first in `states=(...)`.
Its current displayed text is `.label` (NOT `.checked`, which has confusing inverted semantics
internal to the widget and is deliberately not used here). `InputField`/`Label` both expose a
plain `.value` string attribute.
"""

from __future__ import annotations

import argparse
import threading
from pathlib import Path
from typing import Any

import pytermgui as ptg

from scribe import pipeline
from scribe.gui.app import build_config, resolve_form_defaults
from scribe.pipeline import (
    CostConfirmationRequiredError,
    OverwriteConfirmationRequiredError,
    TokenEstimateConfirmationRequiredError,
)
from scribe.project.presets import load_presets, save_preset

_CONFIRMATION_EXCEPTIONS = (
    TokenEstimateConfirmationRequiredError,
    OverwriteConfirmationRequiredError,
    CostConfirmationRequiredError,
)


def build_prototype_window(repo_path: Path, manager: ptg.WindowManager) -> ptg.Window:
    """Build the (not-yet-shown) window -- split out from `run_tui_ptg` so it can be
    constructed and inspected in a test without ever entering the blocking render loop."""
    defaults = resolve_form_defaults(repo_path)
    mode_default = defaults.get("mode") or "lean_technical"
    mode_other = "operator_split" if mode_default == "lean_technical" else "lean_technical"

    mode_toggle = ptg.Toggle((mode_default, mode_other))
    output_dir_field = ptg.InputField(str(defaults.get("output_dir") or "docs"), prompt="Output dir: ")
    provider_field = ptg.InputField(str(defaults.get("provider") or ""), prompt="Provider: ")
    model_field = ptg.InputField(str(defaults.get("model") or ""), prompt="Model: ")
    api_key_field = ptg.InputField("", prompt="API key: ")
    max_tokens_field = ptg.InputField(
        "" if defaults.get("max_tokens") is None else str(defaults["max_tokens"]), prompt="Max tokens: "
    )
    temperature_field = ptg.InputField(
        "" if defaults.get("temperature") is None else str(defaults["temperature"]), prompt="Temperature: "
    )
    token_budget_field = ptg.InputField(str(defaults.get("token_budget") or ""), prompt="Token budget: ")
    max_repair_field = ptg.InputField(str(defaults.get("max_repair_attempts") or ""), prompt="Max repairs: ")
    chunked_toggle = ptg.Toggle(("Off", "On"))  # Force chunked generation -- default off
    verbose_toggle = ptg.Toggle(("On", "Off"))  # Verbose logging -- always defaults on
    preset_name_field = ptg.InputField("", prompt="Save as: ")
    log_label = ptg.Label("")
    status_label = ptg.Label("Idle")

    def _current_form() -> dict[str, Any]:
        return {
            "mode": mode_toggle.label,
            "provider": provider_field.value,
            "model": model_field.value,
            "api_key": api_key_field.value,
            "output_dir": output_dir_field.value,
            "max_tokens": max_tokens_field.value,
            "temperature": temperature_field.value,
            "token_budget": token_budget_field.value,
            "max_repair_attempts": max_repair_field.value,
            "chunked": chunked_toggle.label == "On",
        }

    log_lines: list[str] = []

    def _append_log(message: str) -> None:
        log_lines.append(message)
        log_label.value = "\n".join(log_lines[-20:])
        log_label.get_lines()

    def _run_generation(form: dict[str, Any], *, confirmed: bool) -> None:
        try:
            config = build_config(repo_path, form, assume_yes=confirmed)
            written = pipeline.run(config, on_status=_append_log)
            status_label.value = f"Done -- {len(written)} file(s) written."
        except _CONFIRMATION_EXCEPTIONS as exc:
            manager.alert(
                str(exc),
                ["Proceed", lambda *_a: _start_generation(form, confirmed=True)],
                ["Cancel", lambda *_a: status_label.__setattr__("value", "Cancelled.")],
            )
        except Exception as exc:  # deliberately broad: surface ANY pipeline failure, don't crash
            status_label.value = f"Failed: {exc}"

    def _start_generation(form: dict[str, Any], *, confirmed: bool) -> None:
        status_label.value = "Running..."
        threading.Thread(
            target=_run_generation, args=(form,), kwargs={"confirmed": confirmed}, daemon=True
        ).start()

    def _on_generate(*_args: Any) -> None:
        _start_generation(_current_form(), confirmed=False)

    def _on_save_preset(*_args: Any) -> None:
        name = preset_name_field.value.strip()
        if not name:
            status_label.value = "Enter a preset name first."
            return
        save_preset(repo_path, name, _current_form())
        status_label.value = f"Saved preset '{name}'."

    def _load_preset(name: str) -> None:
        # `InputField.value` is a READ-ONLY property (confirmed by introspecting the installed
        # library) -- there's no public setter for its text content, only cursor-relative edit
        # methods (insert_text/delete_back/...). Rather than poking the private `_lines`
        # attribute, this prototype only demonstrates preset loading for the mode toggle (which
        # DOES have a clean way to set its displayed state); a real implementation would need
        # to either find/request a public setter or rebuild the affected widgets.
        preset_defaults = resolve_form_defaults(repo_path, preset_name=name)
        if preset_defaults.get("mode"):
            mode_toggle.label = preset_defaults["mode"]
            mode_toggle.get_lines()
        status_label.value = f"Loaded preset '{name}' (mode only -- see comment in tui_ptg.py)."

    preset_buttons: list[Any] = [
        ptg.Button(name, onclick=lambda *_a, n=name: _load_preset(n)) for name in load_presets(repo_path)
    ]

    window = (
        ptg.Window(
            f"Repo: {repo_path}",
            "",
            ptg.Container("Presets", *preset_buttons) if preset_buttons else "No presets saved yet.",
            ptg.Splitter(preset_name_field, ["Save preset", _on_save_preset]),
            "",
            ptg.Splitter(ptg.Label("Mode:"), mode_toggle),
            output_dir_field,
            provider_field,
            model_field,
            api_key_field,
            ptg.Splitter(max_tokens_field, temperature_field),
            ptg.Splitter(token_budget_field, max_repair_field),
            ptg.Splitter(ptg.Label("Chunked:"), chunked_toggle, ptg.Label("Verbose:"), verbose_toggle),
            "",
            ["Generate", _on_generate],
            status_label,
            "",
            "Log:",
            log_label,
            width=80,
            box="DOUBLE",
        )
        .set_title("S.C.R.I.B.E. (pytermgui prototype)")
        .center()
    )
    return window


def run_tui_ptg(repo_path: Path) -> None:
    with ptg.WindowManager() as manager:
        manager.add(build_prototype_window(repo_path, manager))


def main() -> None:
    parser = argparse.ArgumentParser(description="pytermgui TUI prototype for S.C.R.I.B.E.")
    parser.add_argument("--repo", type=Path, default=Path("."), help="Repo to generate documentation for.")
    args = parser.parse_args()
    run_tui_ptg(args.repo.resolve())


if __name__ == "__main__":
    main()
