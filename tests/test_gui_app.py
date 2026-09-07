"""Tests for the framework-agnostic GUI logic (`gui/app.py`) -- no HTTP/sockets involved."""

from __future__ import annotations

import time

import pytest

from scribe.constants import AudienceMode
from scribe.gui.app import RunState, build_config, resolve_form_defaults, run_generation
from scribe.pipeline import OverwriteConfirmationRequiredError
from scribe.providers.resolution import NoProviderResolvedError


def test_resolve_form_defaults_has_sane_built_in_defaults(tmp_path):
    defaults = resolve_form_defaults(tmp_path)
    assert defaults["mode"] == AudienceMode.LEAN_TECHNICAL.value
    assert defaults["output_dir"] == "docs"
    assert defaults["chunked"] is False


def test_resolve_form_defaults_layers_scribe_toml_over_built_ins(tmp_path):
    (tmp_path / "scribe.toml").write_text('mode = "operator_split"\n', encoding="utf-8")
    defaults = resolve_form_defaults(tmp_path)
    assert defaults["mode"] == "operator_split"


def test_resolve_form_defaults_layers_preset_over_scribe_toml(tmp_path):
    (tmp_path / "scribe.toml").write_text('mode = "operator_split"\n', encoding="utf-8")
    from scribe.project.presets import save_preset

    save_preset(tmp_path, "quick", {"mode": "lean_technical"})
    defaults = resolve_form_defaults(tmp_path, preset_name="quick")
    assert defaults["mode"] == "lean_technical"


def test_resolve_form_defaults_ignores_unknown_preset_name(tmp_path):
    defaults = resolve_form_defaults(tmp_path, preset_name="does-not-exist")
    assert defaults["mode"] == AudienceMode.LEAN_TECHNICAL.value


def test_build_config_resolves_ollama_when_reachable(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    config = build_config(tmp_path, {"mode": "lean_technical", "model": "llama3.1:8b"}, assume_yes=True)
    assert config.provider == "ollama"
    assert config.model == "llama3.1:8b"
    assert config.assume_yes is True
    assert config.output_dir == tmp_path / "docs"


def test_build_config_resolves_relative_output_dir_against_repo_path(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    config = build_config(tmp_path, {"model": "llama3.1:8b", "output_dir": "generated"}, assume_yes=False)
    assert config.output_dir == tmp_path / "generated"


def test_build_config_raises_when_no_model_can_be_resolved(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    monkeypatch.setattr("scribe.gui.app._default_model_for", lambda _provider: None)
    with pytest.raises(NoProviderResolvedError):
        build_config(tmp_path, {}, assume_yes=True)


def test_build_config_parses_optional_numeric_fields(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    config = build_config(
        tmp_path,
        {"model": "llama3.1:8b", "max_tokens": "1234", "temperature": "0.5"},
        assume_yes=True,
    )
    assert config.max_tokens == 1234
    assert config.temperature == 0.5


def test_build_config_leaves_optional_numeric_fields_none_when_blank(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    config = build_config(
        tmp_path, {"model": "llama3.1:8b", "max_tokens": "", "temperature": None}, assume_yes=True
    )
    assert config.max_tokens is None
    assert config.temperature is None


def _fake_resolution():
    from scribe.providers.resolution import ProviderResolution

    return ProviderResolution(provider="ollama", api_key=None)


def test_run_state_snapshot_reflects_progress():
    state = RunState()
    state.reset()
    state.add_message("hello")
    snapshot = state.snapshot()
    assert snapshot["running"] is True
    assert snapshot["messages"] == ["hello"]

    state.finish(written=["docs/a.md"])
    snapshot = state.snapshot()
    assert snapshot["running"] is False
    assert snapshot["done"] is True
    assert snapshot["written"] == ["docs/a.md"]
    assert snapshot["error"] is None


def test_run_generation_success_updates_state(tmp_path, monkeypatch):
    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    monkeypatch.setattr("scribe.gui.app.pipeline.run", lambda config, on_status: [tmp_path / "docs" / "a.md"])
    state = RunState()
    run_generation(tmp_path, {}, state, confirmed=True)
    snapshot = state.snapshot()
    assert snapshot["done"] is True
    assert snapshot["error"] is None
    assert snapshot["written"] == [str(tmp_path / "docs" / "a.md")]


def test_run_generation_surfaces_confirmation_required(tmp_path, monkeypatch):
    def _raise(config, on_status):
        raise OverwriteConfirmationRequiredError([tmp_path / "docs" / "README.md"])

    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    monkeypatch.setattr("scribe.gui.app.pipeline.run", _raise)
    state = RunState()
    run_generation(tmp_path, {}, state, confirmed=False)
    snapshot = state.snapshot()
    assert snapshot["confirmation"]["type"] == "overwrite"
    assert snapshot["error"] is None


def test_run_generation_surfaces_unexpected_errors_without_crashing(tmp_path, monkeypatch):
    def _raise(config, on_status):
        raise RuntimeError("boom")

    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    monkeypatch.setattr("scribe.gui.app.pipeline.run", _raise)
    state = RunState()
    run_generation(tmp_path, {}, state, confirmed=True)
    snapshot = state.snapshot()
    assert snapshot["error"] == "boom"
    assert snapshot["done"] is True


def test_run_generation_reports_status_messages_live(tmp_path, monkeypatch):
    def _fake_run(config, on_status):
        on_status("step 1")
        on_status("step 2")
        return []

    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    monkeypatch.setattr("scribe.gui.app.pipeline.run", _fake_run)
    state = RunState()
    run_generation(tmp_path, {}, state, confirmed=True)
    assert state.snapshot()["messages"] == ["step 1", "step 2"]


def test_run_state_reset_clears_previous_run(tmp_path):
    state = RunState()
    state.reset()
    state.add_message("old")
    state.finish(error="old error")

    state.reset()
    snapshot = state.snapshot()
    assert snapshot["messages"] == []
    assert snapshot["error"] is None
    assert snapshot["running"] is True


def test_run_generation_is_thread_safe_enough_to_poll_concurrently(tmp_path, monkeypatch):
    """Not a rigorous concurrency test -- just confirms snapshot() never sees a torn/partial
    state while add_message() is being called from the generation thread."""
    import threading

    def _fake_run(config, on_status):
        for i in range(20):
            on_status(f"msg {i}")
            time.sleep(0.001)
        return []

    monkeypatch.setattr("scribe.gui.app.resolve_provider_and_key", lambda *a, **k: _fake_resolution())
    monkeypatch.setattr("scribe.gui.app.pipeline.run", _fake_run)
    state = RunState()
    thread = threading.Thread(target=run_generation, args=(tmp_path, {}, state), kwargs={"confirmed": True})
    thread.start()
    for _ in range(10):
        snapshot = state.snapshot()
        assert isinstance(snapshot["messages"], list)
        time.sleep(0.002)
    thread.join()
    assert state.snapshot()["done"] is True
