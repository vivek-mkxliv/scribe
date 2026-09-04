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


def test_cross_link_to_a_sibling_page_not_in_this_call_is_not_flagged_dead():
    """Regression test: per-page generation reviews one document at a time, so the known-ids
    set must come from the full doc plan, not just the document(s) passed in this call."""
    documents = {"user-guide/01-execution.md": "See [Troubleshooting](02-troubleshooting.md)."}
    report = review_documents(
        documents, known_doc_ids={"user-guide/01-execution.md", "user-guide/02-troubleshooting.md"}
    )
    assert report.ok


def test_cross_link_resolves_across_nested_folders_by_basename():
    documents = {"cli/01-usage.md": "See [Architecture](../engineering/01-architecture.md)."}
    report = review_documents(documents, known_doc_ids={"cli/01-usage.md", "engineering/01-architecture.md"})
    assert report.ok


def test_genuinely_dead_link_is_still_flagged_with_explicit_known_ids():
    documents = {"README.md": "See [Other Doc](NOT_IN_SUITE.md) for details."}
    report = review_documents(documents, known_doc_ids={"README.md"})
    assert not report.ok
    assert any(issue.category == "dead_link" for issue in report.issues)


def test_mermaid_block_of_only_style_directives_is_not_flagged():
    """Regression test: a real local model split a diagram's classDef legend into its own
    separate ```mermaid block instead of inline -- that's a real (if non-standard) pattern,
    not a broken diagram, and shouldn't burn a repair round every time it happens."""
    documents = {
        "README.md": (
            "```mermaid\nflowchart TD\nA-->B\n```\n\n"
            "```mermaid\nclassDef box fill:#ddd;\nclass A,B box;\n```\n"
        )
    }
    report = review_documents(documents)
    assert report.ok
