"""Tests for the marker-based section parser/validator/writer."""

from __future__ import annotations

from scribe.generation.writer import parse_sections, validate_sections, write_documents

GOOD_MARKDOWN = (
    '<!-- SCRIBE:BEGIN doc="README.md" -->\nHello world\n<!-- SCRIBE:END -->\n'
    '<!-- SCRIBE:BEGIN doc="USER_MANUAL.md" -->\nManual body\n<!-- SCRIBE:END -->'
)
EXPECTED_IDS = ["README.md", "USER_MANUAL.md"]


def test_parse_sections_extracts_all_bodies():
    sections = parse_sections(GOOD_MARKDOWN)
    assert sections["README.md"] == ["Hello world"]
    assert sections["USER_MANUAL.md"] == ["Manual body"]


def test_validate_sections_all_present_is_ok():
    result = validate_sections(GOOD_MARKDOWN, EXPECTED_IDS)
    assert result.ok
    assert result.missing == []
    assert result.found["README.md"] == "Hello world"


def test_validate_sections_reports_missing_by_name():
    only_readme = '<!-- SCRIBE:BEGIN doc="README.md" -->\nHello\n<!-- SCRIBE:END -->'
    result = validate_sections(only_readme, EXPECTED_IDS)
    assert not result.ok
    assert result.missing == ["USER_MANUAL.md"]


def test_validate_sections_reports_duplicates_by_name():
    duplicated = GOOD_MARKDOWN + '\n<!-- SCRIBE:BEGIN doc="README.md" -->\nAgain\n<!-- SCRIBE:END -->'
    result = validate_sections(duplicated, EXPECTED_IDS)
    assert not result.ok
    assert result.duplicated == ["README.md"]


def test_a_stray_markdown_horizontal_rule_does_not_break_parsing():
    markdown_with_hr = (
        '<!-- SCRIBE:BEGIN doc="README.md" -->\nSome text\n\n---\n\nMore text\n<!-- SCRIBE:END -->\n'
        '<!-- SCRIBE:BEGIN doc="USER_MANUAL.md" -->\nManual body\n<!-- SCRIBE:END -->'
    )
    result = validate_sections(markdown_with_hr, EXPECTED_IDS)
    assert result.ok
    assert "---" in result.found["README.md"]


def test_write_documents_creates_expected_files(tmp_path):
    documents = {"README.md": "Hello", "USER_MANUAL.md": "Manual"}
    written = write_documents(documents, tmp_path, EXPECTED_IDS)
    assert [p.name for p in written] == EXPECTED_IDS
    assert (tmp_path / "README.md").read_text(encoding="utf-8").strip() == "Hello"


def test_write_documents_creates_nested_folders_for_sectioned_doc_ids(tmp_path):
    """Dynamic doc plans (see `generation/doc_plan.py`) can produce doc ids with a folder
    prefix, e.g. "user-guides/01-gui.md" -- the parent directory must be created on demand."""
    doc_ids = ["user-guides/01-gui.md", "user-guides/02-cli.md", "dev-docs/architecture.md"]
    documents = {doc_id: f"Body for {doc_id}" for doc_id in doc_ids}
    written = write_documents(documents, tmp_path, doc_ids)

    assert {str(p.relative_to(tmp_path).as_posix()) for p in written} == set(doc_ids)
    for doc_id in doc_ids:
        assert (tmp_path / doc_id).read_text(encoding="utf-8").strip() == f"Body for {doc_id}"
