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
    assert fake_client.call_count == 5  # one plan-derivation call + one call per page (4 pages)

    statuses: list[str] = []
    written = run(config, on_status=statuses.append)

    assert fake_client.call_count == 5  # not called again
    assert any("skipping" in message.lower() for message in statuses)
    assert {p.name for p in written} == set(DOC_SUITE[AudienceMode.LEAN_TECHNICAL])


def test_changed_repo_triggers_regeneration_not_skip(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 5

    _write(tmp_path / "repo" / "b.py", "import sys\n")
    run(config)
    # The doc plan is keyed by stable repo identity (not content hash), so it's reused across
    # content changes -- only 4 more page-generation calls, not another plan-derivation call too.
    assert fake_client.call_count == 9


def test_no_incremental_flag_forces_regeneration(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    run(_config(tmp_path, assume_yes=True, incremental=False))
    # Same (unchanged) repo hash -> the plan is served from cache on the second run, so only
    # 4 more calls (one per page) are made, not another plan-derivation call.
    assert fake_client.call_count == 9


def test_doc_plan_structure_survives_content_changes_without_refresh_plan(tmp_path, monkeypatch):
    """The doc plan is keyed by stable repo identity, not content hash -- a content change
    should never reshuffle/rename the generated structure on its own."""
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    written_first = run(config)

    _write(tmp_path / "repo" / "b.py", "import sys\n")
    written_second = run(config)

    assert {p.name for p in written_first} == {p.name for p in written_second}


def test_refresh_plan_forces_a_fresh_plan_derivation_even_when_unchanged(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 5

    run(_config(tmp_path, assume_yes=True, refresh_plan=True))
    # Unchanged repo, but --refresh-plan forces a new plan-derivation call plus 4 page calls.
    assert fake_client.call_count == 10


def test_durable_plan_file_is_reused_even_with_a_fresh_cache_dir(tmp_path, monkeypatch):
    """Simulates a different machine / fresh clone: the plan is reused from the repo-durable
    output_dir/.scribe_plan.json (meant to be committed), not just the local ~/.scribe_cache."""
    _write(tmp_path / "repo" / "a.py", "import os\n")
    fake_client = FakeLLMClient()
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 5  # 1 plan + 4 pages

    _write(tmp_path / "repo" / "b.py", "import sys\n")  # force past the top-level full-skip
    fresh_cache_config = _config(tmp_path, assume_yes=True, cache_dir=tmp_path / "a_totally_different_cache")
    run(fresh_cache_config)
    # Plan reused from output_dir/.scribe_plan.json despite the fresh cache_dir -> only 4 more
    # page calls, no new plan-derivation call.
    assert fake_client.call_count == 9


_STALENESS_PLAN_RESPONSE = json.dumps(
    {
        "mode": "lean_technical",
        "rationale": "test",
        "sections": [
            {
                "id": "pages",
                "title": "Pages",
                "pages": [
                    {"id": "pages/page-a.md", "title": "Page A", "sources": ["a.py"]},
                    {"id": "pages/page-b.md", "title": "Page B", "sources": ["b.py"]},
                ],
            }
        ],
    }
)


class _StalenessFakeLLMClient:
    """Responds per-page based on which doc id appears in the "Your Assignment" prompt slot.

    Both page ids appear in every per-page prompt (one in "Your Assignment", the other in the
    "Full Documentation Plan" cross-link listing) -- must scope the match to the assignment
    section, not just check substring presence anywhere in the prompt.
    """

    def __init__(self, tag: str) -> None:
        self.call_count = 0
        self.tag = tag
        self.generated_ids: list[str] = []

    def complete(self, prompt: str, model: str, **_kwargs) -> str:
        self.call_count += 1
        if PLANNER_MARKER in prompt:
            return _STALENESS_PLAN_RESPONSE
        assignment_index = prompt.rfind("Your Assignment")
        tail = prompt[assignment_index:] if assignment_index != -1 else prompt
        for doc_id in ("pages/page-a.md", "pages/page-b.md"):
            if f'doc="{doc_id}"' in tail:
                self.generated_ids.append(doc_id)
                return (
                    f'<!-- SCRIBE:BEGIN doc="{doc_id}" -->\n'
                    f"Content for {doc_id} ({self.tag})\n"
                    "<!-- SCRIBE:END -->"
                )
        raise AssertionError(f"Unrecognized prompt: {prompt[:200]!r}")


def test_per_page_staleness_skips_pages_whose_sources_are_unchanged(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    _write(tmp_path / "repo" / "b.py", "import sys\n")
    fake_client = _StalenessFakeLLMClient("v1")
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 3  # 1 plan + 2 pages
    assert set(fake_client.generated_ids) == {"pages/page-a.md", "pages/page-b.md"}

    page_b_first = (tmp_path / "repo" / "docs" / "pages" / "page-b.md").read_text(encoding="utf-8")

    # Only a.py changes; b.py (page-b's source) is untouched.
    _write(tmp_path / "repo" / "a.py", "import os\nimport sys\n")
    fake_client.generated_ids.clear()
    run(config)

    # Plan reused (durable .scribe_plan.json); page-b skipped since b.py didn't change.
    assert fake_client.call_count == 4  # +1, for page-a only
    assert fake_client.generated_ids == ["pages/page-a.md"]
    page_b_second = (tmp_path / "repo" / "docs" / "pages" / "page-b.md").read_text(encoding="utf-8")
    assert page_b_second == page_b_first


def test_no_incremental_flag_disables_per_page_staleness_too(tmp_path, monkeypatch):
    _write(tmp_path / "repo" / "a.py", "import os\n")
    _write(tmp_path / "repo" / "b.py", "import sys\n")
    fake_client = _StalenessFakeLLMClient("v1")
    monkeypatch.setattr(llm_client, "build_client", lambda *a, **k: fake_client)

    config = _config(tmp_path, assume_yes=True)
    run(config)
    assert fake_client.call_count == 3

    fake_client.generated_ids.clear()
    run(_config(tmp_path, assume_yes=True, incremental=False))
    # Nothing changed, but --no-incremental regenerates every page regardless of staleness.
    assert set(fake_client.generated_ids) == {"pages/page-a.md", "pages/page-b.md"}


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
