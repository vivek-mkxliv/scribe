"""Tests for the post-generation QA pass (mermaid validity, dead links, placeholders)."""

from __future__ import annotations

from scribe.generation.qa import review_documents


def test_clean_documents_pass():
    documents = {
        "README.md": "# Hello\n\n```mermaid\nflowchart TD\nA-->B\n```\n",
        "USER_MANUAL.md": "See [README](README.md) for more.",
    }
    report = review_documents(documents)
    assert report.ok


def test_unbalanced_mermaid_brackets_are_flagged():
    documents = {"README.md": "```mermaid\nflowchart TD\nA[Start-->B\n```\n"}
    report = review_documents(documents)
    assert not report.ok
    assert any(issue.category == "mermaid" for issue in report.issues)


def test_unrecognized_diagram_type_is_flagged():
    documents = {"README.md": "```mermaid\nnotARealDiagramType\nA-->B\n```\n"}
    report = review_documents(documents)
    assert not report.ok
    assert any(issue.category == "mermaid" for issue in report.issues)


def test_dead_internal_link_is_flagged():
    documents = {"README.md": "See [Other Doc](NOT_IN_SUITE.md) for details."}
    report = review_documents(documents)
    assert not report.ok
    assert any(issue.category == "dead_link" for issue in report.issues)


def test_placeholder_text_is_flagged():
    documents = {"README.md": "TODO: write this section later."}
    report = review_documents(documents)
    assert not report.ok
    assert any(issue.category == "placeholder" for issue in report.issues)


def test_external_links_are_not_flagged_as_dead():
    documents = {"README.md": "See [external](https://example.com/docs) for details."}
    report = review_documents(documents)
    assert report.ok
