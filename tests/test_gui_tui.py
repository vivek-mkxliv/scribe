"""Smoke tests for the Textual TUI (`gui/tui.py`) -- opt-in `tui` extra.

Uses Textual's own `App.run_test()` harness (an async context manager) run via a plain
`asyncio.run()` wrapper, deliberately avoiding a `pytest-asyncio` dev dependency for a handful
of smoke tests. These check that the app composes correctly, preset save/delete works, and a
generate click reaches `pipeline.run()` -- not full UI snapshot testing.
"""

from __future__ import annotations

import asyncio

from textual.widgets import Input, Select, Static, Switch

from scribe.config import ScribeConfig
from scribe.constants import AudienceMode
from scribe.gui.tui import ScribeTuiApp
from scribe.project.presets import load_presets


def _run(coro):
    return asyncio.run(coro)


def _fake_build_config(repo_path, form, *, assume_yes):
    return ScribeConfig(
        repo_path=repo_path,
        output_dir=repo_path / "docs",
        mode=AudienceMode.LEAN_TECHNICAL,
        provider="ollama",
        model="llama3.1:8b",
        api_key=None,
        assume_yes=assume_yes,
    )


async def _wait_until(pilot, predicate, *, attempts: int = 50) -> bool:
    for _ in range(attempts):
        if predicate():
            return True
        await pilot.pause()
    return False


def test_app_mounts_with_sane_defaults(tmp_path):
    async def scenario():
        app = ScribeTuiApp(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            assert app.query_one("#mode", Select).value == "lean_technical"
            assert app.query_one("#outputDir", Input).value == "docs"
            assert app.query_one("#chunked", Switch).value is False
            assert app.query_one("#verbose", Switch).value is True

    _run(scenario())


def test_app_loads_scribe_toml_defaults(tmp_path):
    (tmp_path / "scribe.toml").write_text('mode = "operator_split"\n', encoding="utf-8")

    async def scenario():
        app = ScribeTuiApp(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            assert app.query_one("#mode", Select).value == "operator_split"

    _run(scenario())


def test_save_preset_button_writes_a_preset(tmp_path):
    async def scenario():
        app = ScribeTuiApp(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            app.query_one("#presetName", Input).value = "quick-draft"
            await pilot.click("#savePreset")
            await pilot.pause()
            assert "quick-draft" in load_presets(tmp_path)
            assert "Saved preset" in str(app.query_one("#statusLine", Static).visual)

    _run(scenario())


def test_delete_preset_button_removes_it(tmp_path):
    from scribe.project.presets import save_preset

    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})

    async def scenario():
        app = ScribeTuiApp(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            select = app.query_one("#presetSelect", Select)
            select.value = "quick-draft"
            await pilot.pause()
            await pilot.click("#deletePreset")
            await pilot.pause()
            assert "quick-draft" not in load_presets(tmp_path)

    _run(scenario())


def test_generate_button_reaches_pipeline_run_and_reports_done(tmp_path, monkeypatch):
    written_path = tmp_path / "docs" / "README.md"
    monkeypatch.setattr("scribe.gui.tui.pipeline.run", lambda config, on_status: [written_path])
    monkeypatch.setattr("scribe.gui.tui.build_config", _fake_build_config)

    async def scenario():
        app = ScribeTuiApp(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#generate")
            done = await _wait_until(
                pilot, lambda: "Done" in str(app.query_one("#statusLine", Static).visual)
            )
            assert done, "generation never reported completion"

    _run(scenario())


def test_generate_surfaces_confirmation_required(tmp_path, monkeypatch):
    from scribe.pipeline import OverwriteConfirmationRequiredError

    def _raise(config, on_status):
        raise OverwriteConfirmationRequiredError([tmp_path / "docs" / "README.md"])

    monkeypatch.setattr("scribe.gui.tui.pipeline.run", _raise)
    monkeypatch.setattr("scribe.gui.tui.build_config", _fake_build_config)

    async def scenario():
        app = ScribeTuiApp(tmp_path)
        async with app.run_test(size=(120, 60)) as pilot:
            await pilot.pause()
            await pilot.click("#generate")
            shown = await _wait_until(pilot, lambda: app.query_one("#confirmBox").has_class("visible"))
            assert shown, "confirmation box never appeared"

    _run(scenario())
