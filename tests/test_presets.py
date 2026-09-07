"""Tests for `scribe.presets.json` (`project/presets.py`)."""

from __future__ import annotations

import json

import pytest

from scribe.project.presets import (
    PresetError,
    delete_preset,
    load_preset,
    load_presets,
    presets_path,
    save_preset,
)


def test_load_presets_returns_empty_dict_when_file_missing(tmp_path):
    assert load_presets(tmp_path) == {}


def test_save_then_load_round_trips(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical", "provider": "ollama"})
    assert load_presets(tmp_path) == {"quick-draft": {"mode": "lean_technical", "provider": "ollama"}}
    assert load_preset(tmp_path, "quick-draft") == {"mode": "lean_technical", "provider": "ollama"}


def test_load_preset_returns_none_for_unknown_name(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    assert load_preset(tmp_path, "does-not-exist") is None


def test_saving_a_second_preset_preserves_the_first(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    save_preset(tmp_path, "thorough-audit", {"mode": "operator_split"})
    presets = load_presets(tmp_path)
    assert set(presets) == {"quick-draft", "thorough-audit"}
    assert presets["quick-draft"] == {"mode": "lean_technical"}
    assert presets["thorough-audit"] == {"mode": "operator_split"}


def test_saving_the_same_name_again_overwrites_it(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    save_preset(tmp_path, "quick-draft", {"mode": "operator_split"})
    assert load_preset(tmp_path, "quick-draft") == {"mode": "operator_split"}


def test_unknown_fields_are_dropped_not_errors(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical", "not_a_real_field": 123})
    assert load_preset(tmp_path, "quick-draft") == {"mode": "lean_technical"}


def test_saving_a_raw_api_key_is_refused(tmp_path):
    with pytest.raises(PresetError):
        save_preset(tmp_path, "quick-draft", {"api_key": "sk-should-never-be-here"})
    assert not presets_path(tmp_path).exists()


def test_saving_a_blank_api_key_is_not_refused(tmp_path):
    """Regression test: the GUI/TUI always include an `api_key` key in the values dict they
    submit (blank if the field was left empty) -- the guard must only fire for an actual
    secret, not merely the key's presence, or every preset save from those UIs would fail."""
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical", "api_key": ""})
    assert load_preset(tmp_path, "quick-draft") == {"mode": "lean_technical"}


def test_corrupt_json_file_is_treated_as_no_presets(tmp_path):
    presets_path(tmp_path).write_text("not valid json {{{", encoding="utf-8")
    assert load_presets(tmp_path) == {}


def test_delete_preset_removes_it_and_reports_it_existed(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    save_preset(tmp_path, "thorough-audit", {"mode": "operator_split"})

    assert delete_preset(tmp_path, "quick-draft") is True
    assert load_presets(tmp_path) == {"thorough-audit": {"mode": "operator_split"}}


def test_delete_preset_returns_false_when_absent_and_is_a_no_op(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    assert delete_preset(tmp_path, "does-not-exist") is False
    assert load_presets(tmp_path) == {"quick-draft": {"mode": "lean_technical"}}


def test_deleting_the_last_preset_removes_the_file(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    assert delete_preset(tmp_path, "quick-draft") is True
    assert not presets_path(tmp_path).exists()


def test_file_format_is_plain_readable_json(tmp_path):
    save_preset(tmp_path, "quick-draft", {"mode": "lean_technical"})
    raw = json.loads(presets_path(tmp_path).read_text(encoding="utf-8"))
    assert raw == {"presets": {"quick-draft": {"mode": "lean_technical"}}}
