"""Tests for cost-confirmation gating and chunked map-reduce generation in `pipeline.run`."""

from __future__ import annotations

import json

import pytest

from scribe.config import ScribeConfig
from scribe.constants import DOC_SUITE, AudienceMode
from scribe.generation.doc_plan import PLANNER_MARKER, heuristic_doc_plan
from scribe.pipeline import CostConfirmationRequiredError, _build_bounded_digest_text, run
from scribe.providers import llm_client

PLAN_RESPONSE = json.dumps(
    {
        "mode": "lean_technical",
        "rationale": "test plan",
        "sections": [
            {
                "id": "general",
                "title": "Documentation",
                "pages": [
                    {"id": doc_id, "title": doc_id} for doc_id in DOC_SUITE[AudienceMode.LEAN_TECHNICAL]
                ],
            }
        ],
    }
)


class FakeLLMClient:
    """Returns a fixed marker-formatted doc suite for any prompt, a valid doc plan for a
    planning-prompt, or a plain summary string when the prompt looks like a chunking
    package-summary request."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def complete(
        self, prompt: str, model: str, *, temperature: float | None = None, max_tokens: int | None = None
    ) -> str:
        self.calls.append(prompt)
        if PLANNER_MARKER in prompt:
            return PLAN_RESPONSE
        if "Summarize this subsystem" in prompt:
            return "A one-paragraph summary of this package."
        return "\n".join(
            f'<!-- SCRIBE:BEGIN doc="{doc_id}" -->\nBody for {doc_id}\n<!-- SCRIBE:END -->'
            for doc_id in ("README.md", "USER_MANUAL.md", "TROUBLESHOOTING.md", "DEV_PLAYBOOK.md")
        )


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _base_config(tmp_path, **overrides) -> ScribeConfig:
    defaults = {
        "repo_path": tmp_path / "repo",
        "output_dir": tmp_path / "repo" / "docs",
        "mode": AudienceMode.LEAN_TECHNICAL,
        "provider": "ollama",  # no API key required, avoids needing real credentials in tests
        "model": "llama3.1:8b",
        "api_key": None,
        "force_native_extractor": True,
        "cache_dir": tmp_path / "cache",
    }
    defaults.update(overrides)
    return ScribeConfig(**defaults)


def test_run_raises_cost_confirmation_when_chunked_forced_without_assume_yes(tmp_path):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    config = _base_config(tmp_path, chunked=True, assume_yes=False)

    with pytest.raises(CostConfirmationRequiredError) as exc_info:
        run(config)
    assert exc_info.value.chunked is True


def test_run_proceeds_with_chunked_generation_when_assume_yes(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "pkg" / "a.py", "import os\n")
    _write(tmp_path / "repo" / "pkg" / "b.py", "import sys\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _base_config(tmp_path, chunked=True, assume_yes=True)
    written = run(config)

    assert {p.name for p in written} == {
        "README.md",
        "USER_MANUAL.md",
        "TROUBLESHOOTING.md",
        "DEV_PLAYBOOK.md",
    }
    # At least one package-summary call plus the final synthesis call.
    assert any("Summarize this subsystem" in call for call in fake_client.calls)
    assert any("Summarize this subsystem" not in call for call in fake_client.calls)


def test_build_bounded_digest_text_reports_still_over_budget_when_absurdly_tight():
    from scribe.extraction.models import GraphContext, GraphStats, ModuleNode

    context = GraphContext(
        modules=[ModuleNode(path="a.py", language="python", loc=1)],
        edges=[],
        entry_points=[],
        stats=GraphStats(file_count=1, total_loc=1, languages={"python": 1}),
        source="native_fallback",
    )
    _digest_text, _tokens, still_over = _build_bounded_digest_text(
        "project context",
        context,
        heuristic_doc_plan(AudienceMode.LEAN_TECHNICAL),
        token_budget=1,
        on_status=lambda _m: None,
    )
    assert still_over is True
