"""Tests for `GraphContext`'s prompt-digest rendering, including truncation above budget."""

from __future__ import annotations

from scribe.extraction.models import DependencyEdge, GraphContext, GraphStats, ModuleNode


def _make_context(module_count: int) -> GraphContext:
    modules = [ModuleNode(path=f"m_{i}.py", language="python", loc=10) for i in range(module_count)]
    # Chain edges so later modules have higher fan-in/out and are "more connected".
    edges = [DependencyEdge(source=f"m_{i}.py", target=f"m_{i + 1}.py") for i in range(module_count - 1)]
    stats = GraphStats(
        file_count=module_count, total_loc=module_count * 10, languages={"python": module_count}
    )
    return GraphContext(modules=modules, edges=edges, entry_points=[], stats=stats, source="native_fallback")


def test_to_prompt_text_includes_all_modules_below_the_cap():
    context = _make_context(10)
    text = context.to_prompt_text(max_modules=50)
    assert text.count(".py (python") == 10
    assert "truncated" not in text.lower()


def test_to_prompt_text_collapses_above_the_cap():
    context = _make_context(50)
    text = context.to_prompt_text(max_modules=10)
    assert text.count(".py (python") == 10
    assert "truncated to the 10 most-connected modules out of 50 total" in text


def test_to_prompt_text_drops_edges_between_truncated_modules():
    context = _make_context(50)
    text = context.to_prompt_text(max_modules=5)
    # Every edge line must reference only modules that survived truncation.
    kept_paths = {
        line.split(" ")[1] for line in text.splitlines() if line.startswith("- m_") and ".py (" in line
    }
    for line in text.splitlines():
        if "->" in line and line.startswith("-"):
            source, target = (p.strip("- ") for p in line.split("->"))
            assert source in kept_paths
            assert target in kept_paths
