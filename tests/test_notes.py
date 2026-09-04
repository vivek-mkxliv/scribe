"""Tests for optional, user-authored standing notes (`project/notes.py`)."""

from __future__ import annotations

from scribe.project.notes import NOTES_FILENAME, load_scribe_notes, notes_path


def test_load_scribe_notes_when_file_absent_says_so_explicitly(tmp_path):
    text = load_scribe_notes(tmp_path)
    assert NOTES_FILENAME in text
    assert "no standing notes" in text.lower()


def test_load_scribe_notes_renders_file_content(tmp_path):
    path = notes_path(tmp_path)
    path.write_text("Always keep exactly one FAQ page; never split the CLI section.", encoding="utf-8")

    text = load_scribe_notes(tmp_path)

    assert "Always keep exactly one FAQ page" in text
    assert "no standing notes" not in text.lower()


def test_load_scribe_notes_treats_empty_file_as_unavailable(tmp_path):
    path = notes_path(tmp_path)
    path.write_text("   \n\n", encoding="utf-8")

    text = load_scribe_notes(tmp_path)

    assert "unavailable" in text.lower()
