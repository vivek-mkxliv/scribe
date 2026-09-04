"""Tests for the native (Graphifyy-free) multi-language extractor and content cache.

Every cache-related call passes an explicit `cache_root`/`cache_dir` under
`tmp_path` so tests never touch the real user-level cache directory
(`~/.scribe_cache`) that's used by default outside of tests.
"""

from __future__ import annotations

import json
import subprocess

import pytest

from scribe.extraction import extractor
from scribe.extraction.cache import (
    compute_repo_hash,
    load_cached_context,
    repo_identity_key,
    store_cached_context,
)
from scribe.extraction.extractor import (
    MAX_NATIVE_FILES,
    GraphifyyContractError,
    GraphifyyMissingAction,
    GraphifyyNotFoundError,
    _find_graphify_executable,
    build_native_context,
    extract_context,
    manual_graphifyy_command,
    parse_graphifyy_output,
)
from scribe.extraction.models import DependencyEdge


def test_find_graphify_executable_prefers_the_current_interpreters_directory(tmp_path, monkeypatch):
    """Regression test: a bare `shutil.which()` misses `graphify` when it's installed
    in the same venv as scribe but that venv isn't "activated" (not prepended to PATH) --
    which is exactly how this CLI is invoked via a direct interpreter path."""
    fake_interpreter_dir = tmp_path / "Scripts"
    fake_interpreter_dir.mkdir()
    fake_graphify = fake_interpreter_dir / "graphify.exe"
    fake_graphify.write_text("", encoding="utf-8")

    monkeypatch.setattr("sys.executable", str(fake_interpreter_dir / "python.exe"))
    monkeypatch.setattr("os.name", "nt")
    monkeypatch.setattr("shutil.which", lambda _name: None)  # PATH lookup must not be needed

    assert _find_graphify_executable() == str(fake_graphify)


def test_find_graphify_executable_falls_back_to_path(tmp_path, monkeypatch):
    # Point at an interpreter dir with no graphify binary so the interpreter-relative
    # check genuinely misses and falls through to the PATH lookup being tested.
    monkeypatch.setattr("sys.executable", str(tmp_path / "python.exe"))
    monkeypatch.setattr("shutil.which", lambda name: f"/usr/bin/{name}" if name == "graphify" else None)
    assert _find_graphify_executable() == "/usr/bin/graphify"


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_build_native_context_resolves_python_imports(tmp_path):
    _write(tmp_path / "pkg" / "a.py", "import pkg.b\n\ndef f():\n    return pkg.b.g()\n")
    _write(tmp_path / "pkg" / "b.py", "def g():\n    return 1\n")

    context = build_native_context(tmp_path)

    assert context.source == "native_fallback"
    module_paths = {m.path for m in context.modules}
    assert "pkg/a.py" in module_paths
    assert "pkg/b.py" in module_paths
    assert context.stats.file_count == 2
    assert context.stats.languages == {"python": 2}


def test_build_native_context_handles_csharp_using_statements(tmp_path):
    _write(tmp_path / "Program.cs", "using System;\nusing MyApp.Services;\n\nclass Program {}\n")
    _write(tmp_path / "Services.cs", "namespace MyApp.Services { class Services {} }\n")

    context = build_native_context(tmp_path)

    assert context.stats.languages == {"csharp": 2}


def test_build_native_context_skips_unreal_and_unity_build_directories(tmp_path):
    _write(tmp_path / "Source" / "Game.cpp", '#include "Game.h"\n')
    _write(tmp_path / "Intermediate" / "Junk.cpp", "garbage that should never be scanned\n")
    _write(tmp_path / "Saved" / "Other.cpp", "also garbage\n")
    _write(tmp_path / "Library" / "Unity.cs", "class ShouldNotAppear {}\n")

    context = build_native_context(tmp_path)

    module_paths = {m.path for m in context.modules}
    assert "Source/Game.cpp" in module_paths
    assert not any(p.startswith(("Intermediate/", "Saved/", "Library/")) for p in module_paths)


def test_build_native_context_reports_truncation_over_the_file_cap(tmp_path):
    for i in range(MAX_NATIVE_FILES + 5):
        _write(tmp_path / f"m_{i:05d}.py", "x = 1\n")

    statuses: list[str] = []
    context = build_native_context(tmp_path, on_status=statuses.append)

    assert context.stats.file_count == MAX_NATIVE_FILES
    assert any("cap" in message.lower() for message in statuses)


def test_repo_identity_key_is_stable_and_content_independent(tmp_path):
    repo_dir = tmp_path / "repo"
    _write(repo_dir / "a.py", "import os\n")

    key_before = repo_identity_key(repo_dir)
    _write(repo_dir / "b.py", "import sys\n")  # content changes, path doesn't
    key_after = repo_identity_key(repo_dir)

    assert key_before == key_after


def test_repo_identity_key_differs_across_repos(tmp_path):
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()
    assert repo_identity_key(repo_a) != repo_identity_key(repo_b)


def test_cache_round_trip_stores_and_loads(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")
    repo_hash = compute_repo_hash(repo_dir)

    assert load_cached_context(repo_dir, repo_hash, cache_root=cache_dir) is None

    context = build_native_context(repo_dir)
    store_cached_context(repo_dir, repo_hash, context, cache_root=cache_dir)

    cached = load_cached_context(repo_dir, repo_hash, cache_root=cache_dir)
    assert cached is not None
    assert cached.source == "cache"
    assert [m.path for m in cached.modules] == [m.path for m in context.modules]
    # Cache lives under cache_dir, never inside the repo it describes.
    assert not (repo_dir / ".scribe_cache").exists()


def test_extract_context_second_call_hits_cache(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    statuses: list[str] = []
    first = extract_context(repo_dir, force_native=True, cache_dir=cache_dir, on_status=statuses.append)
    assert first.source == "native_fallback"

    statuses.clear()
    second = extract_context(repo_dir, force_native=True, cache_dir=cache_dir, on_status=statuses.append)
    assert second.source == "cache"
    assert any("cached" in message.lower() for message in statuses)


def test_extract_context_changed_repo_invalidates_cache(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")
    first = extract_context(repo_dir, force_native=True, cache_dir=cache_dir)
    assert first.source == "native_fallback"

    _write(repo_dir / "b.py", "import sys\n")
    second = extract_context(repo_dir, force_native=True, cache_dir=cache_dir)
    assert second.source == "native_fallback"  # cache miss, re-extracted, not stale cache hit
    assert second.stats.file_count == 2


def test_extract_context_falls_back_on_graphifyy_timeout(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    def _raise_timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="graphifyy", timeout=1)

    monkeypatch.setattr(extractor, "run_graphifyy", _raise_timeout)

    statuses: list[str] = []
    context = extract_context(repo_dir, cache_dir=cache_dir, on_status=statuses.append)

    assert context.source == "native_fallback"
    assert any("did not finish" in message.lower() for message in statuses)


def test_extract_context_missing_graphifyy_defaults_to_fallback_without_callback(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    def _raise_not_found(*_args, **_kwargs):
        raise GraphifyyNotFoundError("not found")

    monkeypatch.setattr(extractor, "run_graphifyy", _raise_not_found)

    context = extract_context(repo_dir, cache_dir=cache_dir)

    assert context.source == "native_fallback"


def test_extract_context_missing_graphifyy_installs_and_retries(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    calls = {"n": 0}

    def _run_graphifyy_stub(*_args, **_kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise GraphifyyNotFoundError("not found")
        return json.dumps({"directed": False, "multigraph": False, "graph": {}, "nodes": [], "links": []})

    monkeypatch.setattr(extractor, "run_graphifyy", _run_graphifyy_stub)
    monkeypatch.setattr(extractor, "_install_graphifyy", lambda _status: True)

    context = extract_context(
        repo_dir,
        cache_dir=cache_dir,
        on_graphifyy_missing=lambda: GraphifyyMissingAction.INSTALL_AND_RETRY,
    )

    assert calls["n"] == 2
    assert context.source == "graphifyy"


def test_extract_context_missing_graphifyy_declined_install_falls_back(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    def _raise_not_found(*_args, **_kwargs):
        raise GraphifyyNotFoundError("not found")

    monkeypatch.setattr(extractor, "run_graphifyy", _raise_not_found)

    context = extract_context(
        repo_dir,
        cache_dir=cache_dir,
        on_graphifyy_missing=lambda: GraphifyyMissingAction.USE_FALLBACK,
    )

    assert context.source == "native_fallback"


def test_extract_context_failed_run_asks_before_falling_back(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    def _raise_contract_error(*_args, **_kwargs):
        raise GraphifyyContractError("bad output")

    monkeypatch.setattr(extractor, "run_graphifyy", _raise_contract_error)

    seen: list[tuple[str, str]] = []

    def _on_failed(detail: str, manual_command: str) -> bool:
        seen.append((detail, manual_command))
        return True

    context = extract_context(repo_dir, cache_dir=cache_dir, on_graphifyy_failed=_on_failed)

    assert context.source == "native_fallback"
    assert len(seen) == 1
    assert "bad output" in seen[0][0]
    assert seen[0][1] == manual_graphifyy_command(repo_dir)


def test_extract_context_failed_run_reraises_when_user_declines_to_continue(tmp_path, monkeypatch):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    def _raise_contract_error(*_args, **_kwargs):
        raise GraphifyyContractError("bad output")

    monkeypatch.setattr(extractor, "run_graphifyy", _raise_contract_error)

    with pytest.raises(GraphifyyContractError):
        extract_context(repo_dir, cache_dir=cache_dir, on_graphifyy_failed=lambda _d, _c: False)


# --- Real NetworkX node-link `graph.json` schema, verified against the actual graphify tool ---

REAL_SCHEMA_GRAPH_JSON = {
    "directed": False,
    "multigraph": False,
    "graph": {},
    "nodes": [
        {
            "id": "client",
            "label": "client.py",
            "file_type": "code",
            "source_file": "client.py",
            "source_location": "L1",
        },
        {
            "id": "client_init",
            "label": ".__init__()",
            "file_type": "code",
            "source_file": "client.py",
            "source_location": "L17",
        },
        {
            "id": "auth",
            "label": "auth.py",
            "file_type": "code",
            "source_file": "auth.py",
            "source_location": "L1",
        },
    ],
    "links": [
        {
            "source": "client",
            "target": "auth",
            "relation": "imports_from",
            "confidence": "EXTRACTED",
            "source_file": "client.py",
            "weight": 1.0,
        },
        {
            "source": "client",
            "target": "client_init",
            "relation": "contains",
            "confidence": "EXTRACTED",
            "source_file": "client.py",
            "weight": 1.0,
        },
    ],
}


def test_parse_graphifyy_output_real_schema_aggregates_nodes_by_file():
    context = parse_graphifyy_output(json.dumps(REAL_SCHEMA_GRAPH_JSON))

    assert context.source == "graphifyy"
    module_paths = {m.path for m in context.modules}
    assert module_paths == {"client.py", "auth.py"}  # two concept nodes collapse to one file
    assert context.edges == [DependencyEdge(source="client.py", target="auth.py")]


def test_parse_graphifyy_output_invalid_json_raises_contract_error():
    with pytest.raises(GraphifyyContractError):
        parse_graphifyy_output("not json at all {{{")


def test_parse_graphifyy_output_missing_keys_raises_contract_error():
    with pytest.raises(GraphifyyContractError):
        parse_graphifyy_output(json.dumps({"nodes": []}))  # missing "links"


def test_refresh_cache_skips_read_but_still_writes(tmp_path):
    repo_dir = tmp_path / "repo"
    cache_dir = tmp_path / "cache"
    _write(repo_dir / "a.py", "import os\n")

    extract_context(repo_dir, force_native=True, cache_dir=cache_dir)
    repo_hash = compute_repo_hash(repo_dir)
    assert load_cached_context(repo_dir, repo_hash, cache_root=cache_dir) is not None

    statuses: list[str] = []
    result = extract_context(
        repo_dir, force_native=True, cache_dir=cache_dir, refresh_cache=True, on_status=statuses.append
    )

    assert result.source == "native_fallback"  # re-extracted, not read from cache
    assert not any("cached" in message.lower() for message in statuses)
    assert load_cached_context(repo_dir, repo_hash, cache_root=cache_dir) is not None  # still persisted
