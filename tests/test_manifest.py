"""Tests for `.scribe_manifest.json` read/write and freshness checks."""

from __future__ import annotations

from scribe.project.manifest import (
    existing_doc_files,
    is_up_to_date,
    load_manifest,
    manifest_path,
    write_manifest,
)

DOC_IDS = ["README.md", "USER_MANUAL.md"]


def test_load_manifest_returns_none_when_missing(tmp_path):
    assert load_manifest(tmp_path) is None


def test_write_then_load_round_trips(tmp_path):
    write_manifest(tmp_path, "hash123", "lean_technical", DOC_IDS)
    manifest = load_manifest(tmp_path)
    assert manifest is not None
    assert manifest.repo_hash == "hash123"
    assert manifest.mode == "lean_technical"
    assert manifest.doc_ids == DOC_IDS
    assert manifest_path(tmp_path).exists()


def test_load_manifest_tolerates_corrupt_file(tmp_path):
    manifest_path(tmp_path).write_text("not json", encoding="utf-8")
    assert load_manifest(tmp_path) is None


def test_is_up_to_date_true_only_on_exact_hash_and_mode_match(tmp_path):
    write_manifest(tmp_path, "hash123", "lean_technical", DOC_IDS)
    assert is_up_to_date(tmp_path, "hash123", "lean_technical") is True
    assert is_up_to_date(tmp_path, "different_hash", "lean_technical") is False
    assert is_up_to_date(tmp_path, "hash123", "operator_split") is False


def test_is_up_to_date_false_with_no_manifest(tmp_path):
    assert is_up_to_date(tmp_path, "hash123", "lean_technical") is False


def test_existing_doc_files_only_lists_files_that_exist(tmp_path):
    (tmp_path / "README.md").write_text("hi", encoding="utf-8")
    found = existing_doc_files(tmp_path, DOC_IDS)
    assert [p.name for p in found] == ["README.md"]
