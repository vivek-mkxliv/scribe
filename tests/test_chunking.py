"""Tests for `core.chunking`'s per-package grouping and map-reduce digest building."""

from __future__ import annotations

from scribe.extraction.models import DependencyEdge, GraphContext, GraphStats, ModuleNode
from scribe.generation.chunking import build_chunked_digest, group_modules_by_package


def _make_context() -> GraphContext:
    modules = [
        ModuleNode(path="pkg_a/one.py", language="python", loc=10),
        ModuleNode(path="pkg_a/two.py", language="python", loc=10),
        ModuleNode(path="pkg_b/three.py", language="python", loc=10),
        ModuleNode(path="top_level.py", language="python", loc=5),
    ]
    edges = [
        DependencyEdge(source="pkg_a/one.py", target="pkg_a/two.py"),  # within pkg_a
        DependencyEdge(source="pkg_a/one.py", target="pkg_b/three.py"),  # cross-package
    ]
    stats = GraphStats(file_count=4, total_loc=35, languages={"python": 4})
    return GraphContext(modules=modules, edges=edges, entry_points=[], stats=stats, source="native_fallback")


def test_group_modules_by_package_splits_by_top_level_directory():
    packages = group_modules_by_package(_make_context())
    assert set(packages) == {"pkg_a", "pkg_b", "(root)"}
    assert {m.path for m in packages["pkg_a"].modules} == {"pkg_a/one.py", "pkg_a/two.py"}
    assert {m.path for m in packages["(root)"].modules} == {"top_level.py"}


def test_group_modules_by_package_keeps_only_within_package_edges():
    packages = group_modules_by_package(_make_context())
    assert packages["pkg_a"].edges == [DependencyEdge(source="pkg_a/one.py", target="pkg_a/two.py")]
    assert packages["pkg_b"].edges == []  # the cross-package edge was dropped, not misattributed


class _RecordingFakeClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def complete(self, prompt: str, model: str, **_kwargs) -> str:
        self.prompts.append(prompt)
        return f"Summary for prompt mentioning {model}."


def test_build_chunked_digest_calls_once_per_package_and_concatenates():
    client = _RecordingFakeClient()
    statuses: list[str] = []

    digest = build_chunked_digest(client, "test-model", _make_context(), on_status=statuses.append)

    assert len(client.prompts) == 3  # pkg_a, pkg_b, (root)
    assert "### Package: pkg_a" in digest
    assert "### Package: pkg_b" in digest
    assert "### Package: (root)" in digest
    assert any("summarizing 3 package" in message.lower() for message in statuses)
