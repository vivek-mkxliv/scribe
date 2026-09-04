"""Tests for the structure-justification doc and the `revise_doc_plan` revision flow."""

from __future__ import annotations

import json

import pytest

from scribe.config import ScribeConfig
from scribe.constants import DOC_SUITE, AudienceMode
from scribe.generation.doc_plan import PLANNER_MARKER, REVISION_MARKER
from scribe.generation.justification import JUSTIFICATION_FILENAME
from scribe.pipeline import NoExistingPlanError, revise_doc_plan, run
from scribe.project.notes import NOTES_FILENAME
from scribe.providers import llm_client

VALID_RESPONSE = "\n".join(
    f'<!-- SCRIBE:BEGIN doc="{doc_id}" -->\nBody for {doc_id}\n<!-- SCRIBE:END -->'
    for doc_id in DOC_SUITE[AudienceMode.LEAN_TECHNICAL]
)

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

REVISED_PLAN_RESPONSE = json.dumps(
    {
        "mode": "lean_technical",
        "rationale": "Added a security section per request.",
        "sections": [
            {
                "id": "general",
                "title": "Documentation",
                "rationale": "unchanged pages",
                "pages": [
                    {"id": doc_id, "title": doc_id} for doc_id in DOC_SUITE[AudienceMode.LEAN_TECHNICAL]
                ],
            },
            {
                "id": "security",
                "title": "Security",
                "rationale": "Requested explicitly.",
                "pages": [{"id": "security/01-overview.md", "title": "Security Overview"}],
            },
        ],
    }
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _config(tmp_path, **overrides) -> ScribeConfig:
    defaults = {
        "repo_path": tmp_path / "repo",
        "output_dir": tmp_path / "repo" / "docs",
        "mode": AudienceMode.LEAN_TECHNICAL,
        "provider": "ollama",
        "model": "llama3.1:8b",
        "api_key": None,
        "force_native_extractor": True,
        "cache_dir": tmp_path / "cache",
    }
    defaults.update(overrides)
    return ScribeConfig(**defaults)


class _RevisionFakeLLMClient:
    def __init__(self) -> None:
        self.call_count = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str, model: str, **_kwargs) -> str:
        self.call_count += 1
        self.prompts.append(prompt)
        if PLANNER_MARKER in prompt:
            return PLAN_RESPONSE
        if REVISION_MARKER in prompt:
            return REVISED_PLAN_RESPONSE
        return VALID_RESPONSE


def test_first_generation_writes_justification_doc(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = _RevisionFakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)

    justification_path = config.output_dir / JUSTIFICATION_FILENAME
    assert justification_path.exists()
    text = justification_path.read_text(encoding="utf-8")
    assert "test plan" in text  # PLAN_RESPONSE's overall rationale
    assert "Initial generation" in text


def test_routine_rerun_does_not_touch_justification_doc(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = _RevisionFakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    justification_path = config.output_dir / JUSTIFICATION_FILENAME
    first_text = justification_path.read_text(encoding="utf-8")

    _write(tmp_path / "repo" / "b.py", "import sys\n")  # unrelated change, forces past top-level skip
    run(config)

    assert justification_path.read_text(encoding="utf-8") == first_text


def test_revise_doc_plan_requires_an_existing_plan(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = _RevisionFakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    with pytest.raises(NoExistingPlanError):
        revise_doc_plan(config, "add a security section")


def test_revise_doc_plan_updates_plan_and_appends_justification_history(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = _RevisionFakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)  # establishes the initial plan + justification doc

    revised = revise_doc_plan(config, "add a security section")

    assert "security/01-overview.md" in revised.doc_ids
    assert REVISION_MARKER in fake_client.prompts[-1]
    assert "add a security section" in fake_client.prompts[-1]

    plan_on_disk = json.loads((config.output_dir / ".scribe_plan.json").read_text(encoding="utf-8"))
    assert any(section["id"] == "security" for section in plan_on_disk["sections"])

    justification_text = (config.output_dir / JUSTIFICATION_FILENAME).read_text(encoding="utf-8")
    assert "Initial generation" in justification_text  # old entry preserved
    assert "Revision requested: add a security section" in justification_text  # new entry appended
    assert "Added a security section per request." in justification_text  # reflects the new plan


def test_revise_doc_plan_folds_in_standing_notes(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    _write(tmp_path / "repo" / NOTES_FILENAME, "Always keep the CLI section to a single page.")
    fake_client = _RevisionFakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)

    revise_doc_plan(config, "add a security section")

    revision_prompt = fake_client.prompts[-1]
    assert "Always keep the CLI section to a single page." in revision_prompt
