"""Tests for incremental regeneration, overwrite confirmation, and drift-checking."""

from __future__ import annotations

import json

import pytest

from scribe.config import ScribeConfig
from scribe.constants import DOC_SUITE, AudienceMode
from scribe.generation.doc_plan import PLANNER_MARKER
from scribe.pipeline import OverwriteConfirmationRequiredError, check_drift, run
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


class FakeLLMClient:
    def __init__(self) -> None:
        self.call_count = 0

    def complete(self, prompt: str, model: str, **_kwargs) -> str:
        self.call_count += 1
        if PLANNER_MARKER in prompt:
            return PLAN_RESPONSE
        return VALID_RESPONSE


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


def test_second_run_is_skipped_via_incremental_manifest(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 2  # one plan-derivation call + one generation call

    statuses: list[str] = []
    written = run(config, on_status=statuses.append)

    assert fake_client.call_count == 2  # not called again
    assert any("skipping" in message.lower() for message in statuses)
    assert {p.name for p in written} == set(DOC_SUITE[AudienceMode.LEAN_TECHNICAL])


def test_changed_repo_triggers_regeneration_not_skip(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 2

    _write(tmp_path / "repo" / "b.py", "import sys\n")
    run(config)
    assert fake_client.call_count == 4  # new repo hash -> a fresh plan-derivation call too


def test_no_incremental_flag_forces_regeneration(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    run(_config(tmp_path, assume_yes=True, incremental=False))
    # Same (unchanged) repo hash -> the plan is served from cache on the second run, so only
    # one more call (generation) is made, not another plan-derivation call.
    assert fake_client.call_count == 3


def test_overwrite_confirmation_required_for_foreign_files_without_manifest(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    _write(tmp_path / "repo" / "docs" / "README.md", "hand-written, not scribe's")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    with pytest.raises(OverwriteConfirmationRequiredError) as exc_info:
        run(_config(tmp_path, assume_yes=False))
    assert any(p.name == "README.md" for p in exc_info.value.existing_files)


def test_overwrite_confirmation_bypassed_with_assume_yes(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    _write(tmp_path / "repo" / "docs" / "README.md", "hand-written, not scribe's")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    written = run(_config(tmp_path, assume_yes=True))
    assert {p.name for p in written} == set(DOC_SUITE[AudienceMode.LEAN_TECHNICAL])


def test_regenerating_scribes_own_prior_output_never_reprompts(tmp_path, monkeypatch):
    """Once a manifest exists, output_dir is scribe's own; overwriting it again never nags."""
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    run(_config(tmp_path, assume_yes=True))
    _write(tmp_path / "repo" / "b.py", "import sys\n")  # force a real regeneration, not a skip
    run(_config(tmp_path, assume_yes=False))  # no confirmation needed, no exception


def test_check_drift_reports_no_manifest(tmp_path):
    report = check_drift(_config(tmp_path))
    assert report.up_to_date is False
    assert "no manifest" in report.reason


def test_check_drift_reports_up_to_date_after_a_real_run(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: FakeLLMClient())
    run(_config(tmp_path, assume_yes=True))

    report = check_drift(_config(tmp_path))
    assert report.up_to_date is True


def test_check_drift_reports_stale_after_repo_changes(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: FakeLLMClient())
    run(_config(tmp_path, assume_yes=True))

    _write(tmp_path / "repo" / "b.py", "import sys\n")
    report = check_drift(_config(tmp_path))
    assert report.up_to_date is False
    assert "changed" in report.reason
