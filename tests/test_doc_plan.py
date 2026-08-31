"""Tests for the dynamic, repo-derived documentation plan (`generation/doc_plan.py`)."""

from __future__ import annotations

import json

import pytest

from scribe.constants import DOC_SUITE, AudienceMode
from scribe.extraction.models import GraphContext, GraphStats, ModuleNode
from scribe.generation.doc_plan import (
    PLANNER_MARKER,
    DocPlan,
    DocPlanContractError,
    derive_doc_plan_via_llm,
    heuristic_doc_plan,
    load_cached_doc_plan,
    load_user_doc_plan,
    reconcile_doc_plan,
    store_cached_doc_plan,
)

VALID_PLAN_JSON = json.dumps(
    {
        "mode": "operator_split",
        "rationale": "Two workflows detected: CLI and GUI.",
        "sections": [
            {
                "id": "user-guides",
                "title": "User Guides",
                "description": "Execution guides",
                "pages": [
                    {"id": "user-guides/01-cli.md", "title": "CLI Guide", "description": "Using the CLI"},
                    {"id": "user-guides/02-gui.md", "title": "GUI Guide", "description": "Using the GUI"},
                ],
            }
        ],
    }
)


def _graph_context() -> GraphContext:
    return GraphContext(
        modules=[ModuleNode(path="a.py", language="python", loc=10)],
        edges=[],
        entry_points=["a.py"],
        stats=GraphStats(file_count=1, total_loc=10, languages={"python": 1}),
        source="native_fallback",
    )


class ScriptedLLMClient:
    """Returns each entry in `responses` in order, one per `.complete()` call."""

    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.call_count = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str, model: str, **_kwargs) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        return self._responses.pop(0)


def test_doc_plan_json_round_trip():
    plan = DocPlan.from_json(VALID_PLAN_JSON)
    assert plan.mode is AudienceMode.OPERATOR_SPLIT
    assert plan.doc_ids == ["user-guides/01-cli.md", "user-guides/02-gui.md"]

    reloaded = DocPlan.from_json(plan.to_json())
    assert reloaded.doc_ids == plan.doc_ids
    assert reloaded.rationale == plan.rationale


def test_doc_plan_to_prompt_text_includes_every_page():
    plan = DocPlan.from_json(VALID_PLAN_JSON)
    text = plan.to_prompt_text()
    assert 'doc="user-guides/01-cli.md"' in text
    assert 'doc="user-guides/02-gui.md"' in text
    assert "User Guides" in text


def test_doc_plan_rejects_malformed_json():
    with pytest.raises(DocPlanContractError):
        DocPlan.from_json("not json at all")


def test_doc_plan_rejects_missing_pages():
    empty = json.dumps({"mode": "lean_technical", "sections": [{"id": "x", "title": "X", "pages": []}]})
    with pytest.raises(DocPlanContractError):
        DocPlan.from_json(empty)


def test_doc_plan_rejects_duplicate_ids():
    dup = json.dumps(
        {
            "mode": "lean_technical",
            "sections": [
                {
                    "id": "x",
                    "title": "X",
                    "pages": [{"id": "a.md", "title": "A"}, {"id": "a.md", "title": "A again"}],
                }
            ],
        }
    )
    with pytest.raises(DocPlanContractError):
        DocPlan.from_json(dup)


def test_doc_plan_rejects_ids_not_ending_in_md():
    bad = json.dumps(
        {
            "mode": "lean_technical",
            "sections": [{"id": "x", "title": "X", "pages": [{"id": "a.txt", "title": "A"}]}],
        }
    )
    with pytest.raises(DocPlanContractError):
        DocPlan.from_json(bad)


def test_heuristic_doc_plan_matches_doc_suite():
    plan = heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL)
    assert plan.doc_ids == DOC_SUITE[AudienceMode.LEAN_TECHNICAL]
    assert plan.mode is AudienceMode.LEAN_TECHNICAL


def test_derive_doc_plan_via_llm_succeeds_on_first_valid_response():
    client = ScriptedLLMClient([VALID_PLAN_JSON])
    plan = derive_doc_plan_via_llm(
        client, "model", "ctx", _graph_context(), AudienceMode.OPERATOR_SPLIT, on_status=lambda _m: None
    )
    assert plan.doc_ids == ["user-guides/01-cli.md", "user-guides/02-gui.md"]
    assert client.call_count == 1
    assert PLANNER_MARKER in client.prompts[0]


def test_derive_doc_plan_via_llm_recovers_from_one_malformed_response():
    client = ScriptedLLMClient(["not json", VALID_PLAN_JSON])
    statuses: list[str] = []
    plan = derive_doc_plan_via_llm(
        client, "model", "ctx", _graph_context(), AudienceMode.OPERATOR_SPLIT, on_status=statuses.append
    )
    assert plan.doc_ids == ["user-guides/01-cli.md", "user-guides/02-gui.md"]
    assert client.call_count == 2
    assert any("invalid" in message.lower() for message in statuses)


def test_derive_doc_plan_via_llm_falls_back_to_heuristic_after_two_failures():
    client = ScriptedLLMClient(["not json", "still not json"])
    plan = derive_doc_plan_via_llm(
        client, "model", "ctx", _graph_context(), AudienceMode.LEAN_TECHNICAL, on_status=lambda _m: None
    )
    assert plan.doc_ids == DOC_SUITE[AudienceMode.LEAN_TECHNICAL]
    assert client.call_count == 2


def test_reconcile_doc_plan_returns_recommended_when_no_user_plan():
    recommended = heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL)
    assert reconcile_doc_plan(recommended, None) is recommended


def test_reconcile_doc_plan_returns_recommended_without_asking_when_identical():
    recommended = heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL)
    identical = heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL)

    def _fail_if_called(_rec, _user):
        raise AssertionError("on_conflict should not be called when plans already match")

    result = reconcile_doc_plan(recommended, identical, on_conflict=_fail_if_called)
    assert result.doc_ids == recommended.doc_ids


def test_reconcile_doc_plan_defaults_to_user_plan_when_noninteractive():
    recommended = heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL)
    user_plan = DocPlan.from_json(VALID_PLAN_JSON)
    result = reconcile_doc_plan(recommended, user_plan, on_conflict=None)
    assert result is user_plan


def test_reconcile_doc_plan_uses_callback_when_conflicting():
    recommended = heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL)
    user_plan = DocPlan.from_json(VALID_PLAN_JSON)
    result = reconcile_doc_plan(recommended, user_plan, on_conflict=lambda rec, _user: rec)
    assert result is recommended


def test_load_user_doc_plan_from_file(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text(VALID_PLAN_JSON, encoding="utf-8")
    plan = load_user_doc_plan(plan_file, mode=AudienceMode.OPERATOR_SPLIT)
    assert plan.doc_ids == ["user-guides/01-cli.md", "user-guides/02-gui.md"]


def test_load_user_doc_plan_rejects_bad_json(tmp_path):
    plan_file = tmp_path / "plan.json"
    plan_file.write_text("not json", encoding="utf-8")
    with pytest.raises(DocPlanContractError):
        load_user_doc_plan(plan_file, mode=AudienceMode.OPERATOR_SPLIT)


def test_doc_plan_cache_round_trip(tmp_path):
    plan = DocPlan.from_json(VALID_PLAN_JSON)
    store_cached_doc_plan(tmp_path, "hash123", AudienceMode.OPERATOR_SPLIT, plan)

    cached = load_cached_doc_plan(tmp_path, "hash123", AudienceMode.OPERATOR_SPLIT)
    assert cached is not None
    assert cached.doc_ids == plan.doc_ids


def test_doc_plan_cache_miss_returns_none(tmp_path):
    assert load_cached_doc_plan(tmp_path, "nonexistent", AudienceMode.LEAN_TECHNICAL) is None
