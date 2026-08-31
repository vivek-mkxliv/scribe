"""Tests for the LLM repair loop in `pipeline._generate_with_repair`.

Uses a scripted fake client so the repair loop is proven correct without any
real network/API dependency.
"""

from __future__ import annotations

import pytest

from scribe.pipeline import GenerationFailedError, _generate_with_repair

DOC_IDS = ["README.md", "USER_MANUAL.md"]


def _doc(doc_id: str, body: str) -> str:
    return f'<!-- SCRIBE:BEGIN doc="{doc_id}" -->\n{body}\n<!-- SCRIBE:END -->'


VALID_RESPONSE = "\n".join(_doc(doc_id, f"Body for {doc_id}") for doc_id in DOC_IDS)
MISSING_DOC_RESPONSE = _doc("README.md", "Only readme")
CLEAN_MERMAID = "```mermaid\nflowchart TD\nA-->B\n```"
BAD_MERMAID_RESPONSE = "\n".join(
    _doc("README.md", "TODO: fill this in") if doc_id == "README.md" else _doc(doc_id, f"Body for {doc_id}")
    for doc_id in DOC_IDS
)


class FakeLLMClient:
    """Returns each entry in `responses` in order, one per `.complete()` call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0

    def complete(
        self, prompt: str, model: str, *, temperature: float | None = None, max_tokens: int | None = None
    ) -> str:
        self.call_count += 1
        return self._responses.pop(0)


def test_repair_loop_succeeds_immediately_on_valid_response():
    client = FakeLLMClient([VALID_RESPONSE])
    documents = _generate_with_repair(
        client, "prompt", "model", DOC_IDS, max_repair_attempts=2, on_status=lambda _m: None
    )
    assert documents["README.md"] == "Body for README.md"
    assert client.call_count == 1


def test_repair_loop_recovers_from_missing_document():
    client = FakeLLMClient([MISSING_DOC_RESPONSE, VALID_RESPONSE])
    documents = _generate_with_repair(
        client, "prompt", "model", DOC_IDS, max_repair_attempts=2, on_status=lambda _m: None
    )
    assert set(documents) == set(DOC_IDS)
    assert client.call_count == 2


def test_repair_loop_recovers_from_qa_failure():
    client = FakeLLMClient([BAD_MERMAID_RESPONSE, VALID_RESPONSE])
    documents = _generate_with_repair(
        client, "prompt", "model", DOC_IDS, max_repair_attempts=2, on_status=lambda _m: None
    )
    assert documents["README.md"] == "Body for README.md"
    assert client.call_count == 2


def test_repair_loop_raises_after_exhausting_attempts():
    client = FakeLLMClient([MISSING_DOC_RESPONSE, MISSING_DOC_RESPONSE, MISSING_DOC_RESPONSE])
    with pytest.raises(GenerationFailedError):
        _generate_with_repair(
            client, "prompt", "model", DOC_IDS, max_repair_attempts=2, on_status=lambda _m: None
        )
    assert client.call_count == 3
