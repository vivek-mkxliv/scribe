"""Tests for per-page generation, truncation recovery, and graceful per-page failure
(`generation/page_writer.py`).
"""

from __future__ import annotations

import pytest

from scribe.generation.doc_plan import DocPage
from scribe.generation.page_writer import (
    GenerationFailedError,
    generate_pages,
    generate_with_repair,
    looks_truncated,
)

DOC_ID = "guide/01-getting-started.md"


def _doc(doc_id: str, body: str) -> str:
    return f'<!-- SCRIBE:BEGIN doc="{doc_id}" -->\n{body}\n<!-- SCRIBE:END -->'


class ScriptedLLMClient:
    """Returns each entry in `responses` in order, one per `.complete()` call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str, model: str, *, temperature=None, max_tokens=None) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_looks_truncated_detects_unclosed_marker():
    truncated = f'<!-- SCRIBE:BEGIN doc="{DOC_ID}" -->\nSome partial content that never closes'
    assert looks_truncated(truncated, DOC_ID, max_tokens=1000) is True


def test_looks_truncated_false_for_complete_response():
    complete = _doc(DOC_ID, "Full content.")
    assert looks_truncated(complete, DOC_ID, max_tokens=1000) is False


def test_looks_truncated_uses_token_ratio_when_no_markers_at_all():
    near_cap_response = "word " * 500  # no markers present at all
    assert looks_truncated(near_cap_response, DOC_ID, max_tokens=10) is True
    assert looks_truncated("short", DOC_ID, max_tokens=10_000) is False


def test_generate_with_repair_continues_a_truncated_single_page_response():
    """A response with an opening marker but no closing one should trigger a continuation
    call, then validate successfully once the two are concatenated."""
    truncated = f'<!-- SCRIBE:BEGIN doc="{DOC_ID}" -->\nHalf of the content, cut off mid'
    continuation = "-sentence. Here is the rest.\n<!-- SCRIBE:END -->"
    client = ScriptedLLMClient([truncated, continuation])

    documents = generate_with_repair(
        client, "prompt", "model", [DOC_ID], max_repair_attempts=2, on_status=lambda _m: None
    )

    assert DOC_ID in documents
    assert "Here is the rest" in documents[DOC_ID]
    assert client.call_count == 2


def test_generate_with_repair_escalates_token_budget_after_continuations_exhausted():
    """If continuations still don't close the document, retry fresh at a doubled budget."""
    still_truncated = f'<!-- SCRIBE:BEGIN doc="{DOC_ID}" -->\nStill going'
    fresh_success = _doc(DOC_ID, "A complete document produced with more room to work with.")
    # 2 continuation attempts (still truncated both times) + 1 fresh retry that succeeds.
    client = ScriptedLLMClient([still_truncated, still_truncated, still_truncated, fresh_success])

    documents = generate_with_repair(
        client, "prompt", "model", [DOC_ID], max_repair_attempts=2, on_status=lambda _m: None, max_tokens=100
    )

    assert documents[DOC_ID] == "A complete document produced with more room to work with."


def test_generate_with_repair_does_not_apply_truncation_logic_to_multi_page_calls():
    """Truncation recovery only kicks in for single-page calls -- the historical multi-doc
    whole-suite contract (still exercised directly in tests) must behave exactly as before."""
    other_id = "other.md"
    response_missing_end_marker_style_text_only = _doc(DOC_ID, "Body") + "\n" + _doc(other_id, "Other body")
    client = ScriptedLLMClient([response_missing_end_marker_style_text_only])

    documents = generate_with_repair(
        client, "prompt", "model", [DOC_ID, other_id], max_repair_attempts=2, on_status=lambda _m: None
    )
    assert client.call_count == 1  # no continuation call triggered for a 2-doc-id request
    assert set(documents) == {DOC_ID, other_id}


def test_generate_pages_writes_placeholder_for_a_page_that_never_succeeds():
    pages = [DocPage(id=DOC_ID, title="Getting Started", description="intro")]
    always_broken = "no markers at all, never valid"
    client = ScriptedLLMClient([always_broken] * 10)  # exhaust every repair attempt

    documents, failed = generate_pages(
        client,
        "model",
        pages,
        build_prompt_for_page=lambda _page: "prompt",
        max_repair_attempts=1,
        on_status=lambda _m: None,
    )

    assert failed == [DOC_ID]
    assert "Generation failed for this page" in documents[DOC_ID]


def test_generate_pages_succeeds_normally_for_a_well_formed_response():
    pages = [DocPage(id=DOC_ID, title="Getting Started", description="intro")]
    client = ScriptedLLMClient([_doc(DOC_ID, "Real content.")])

    documents, failed = generate_pages(
        client,
        "model",
        pages,
        build_prompt_for_page=lambda _page: "prompt",
        max_repair_attempts=1,
        on_status=lambda _m: None,
    )

    assert failed == []
    assert documents[DOC_ID] == "Real content."


def test_generate_with_repair_still_raises_when_repair_attempts_exhausted():
    client = ScriptedLLMClient(["garbage"] * 10)
    with pytest.raises(GenerationFailedError):
        generate_with_repair(
            client, "prompt", "model", [DOC_ID], max_repair_attempts=1, on_status=lambda _m: None
        )


def test_dead_link_only_issues_are_auto_healed_instead_of_discarding_the_page():
    """Regression test: a real model linked to a file it saw in the Project Context tree
    (not part of the doc suite) -- losing the whole page over one stray link is a bad trade."""
    broken = _doc(DOC_ID, "See [Full Architecture](01-full-architecture.md) for more.")
    client = ScriptedLLMClient([broken, broken, broken])

    documents = generate_with_repair(
        client,
        "prompt",
        "model",
        [DOC_ID],
        max_repair_attempts=2,
        on_status=lambda _m: None,
        known_doc_ids={DOC_ID},
    )

    assert documents[DOC_ID] == "See Full Architecture for more."
    assert client.call_count == 3


def test_dead_link_auto_heal_does_not_apply_when_other_issues_also_present():
    """If a mermaid/placeholder issue is ALSO present, auto-healing the link alone wouldn't
    produce a valid document -- must still exhaust repair attempts and raise."""
    broken = _doc(DOC_ID, "TODO: write this.\n\nSee [Arch](01-full-architecture.md).")
    client = ScriptedLLMClient([broken] * 10)

    with pytest.raises(GenerationFailedError):
        generate_with_repair(
            client,
            "prompt",
            "model",
            [DOC_ID],
            max_repair_attempts=1,
            on_status=lambda _m: None,
            known_doc_ids={DOC_ID},
        )
