"""Tests for loading `[tool.scribe]`/`scribe.toml` project defaults."""

from __future__ import annotations

from scribe.project.config_loader import load_project_config


def test_returns_empty_dict_when_neither_file_exists(tmp_path):
    assert load_project_config(tmp_path) == {}


def test_reads_scribe_toml(tmp_path):
    (tmp_path / "scribe.toml").write_text('mode = "operator_split"\noutput_dir = "site"\n', encoding="utf-8")
    config = load_project_config(tmp_path)
    assert config == {"mode": "operator_split", "output_dir": "site"}


def test_reads_tool_scribe_section_of_pyproject_toml(tmp_path):
    (tmp_path / "pyproject.toml").write_text(
        '[tool.scribe]\nmode = "lean_technical"\nprovider = "groq"\n', encoding="utf-8"
    )
    config = load_project_config(tmp_path)
    assert config == {"mode": "lean_technical", "provider": "groq"}


def test_scribe_toml_takes_precedence_over_pyproject_toml(tmp_path):
    (tmp_path / "scribe.toml").write_text('mode = "operator_split"\n', encoding="utf-8")
    (tmp_path / "pyproject.toml").write_text('[tool.scribe]\nmode = "lean_technical"\n', encoding="utf-8")
    assert load_project_config(tmp_path) == {"mode": "operator_split"}


def test_unknown_keys_are_ignored_not_errors(tmp_path):
    (tmp_path / "scribe.toml").write_text(
        'mode = "lean_technical"\nnot_a_real_field = 123\n', encoding="utf-8"
    )
    assert load_project_config(tmp_path) == {"mode": "lean_technical"}


def test_pyproject_toml_without_tool_scribe_section_returns_empty(tmp_path):
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "other-tool"\n', encoding="utf-8")
    assert load_project_config(tmp_path) == {}
