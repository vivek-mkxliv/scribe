"""Data contracts for the extraction layer.

`GraphContext` is the ONLY shape the rest of the pipeline (prompt assembly,
digesting, caching) ever consumes. Where the data came from -- a real
Graphifyy run, a cached result, or the native fallback extractor -- is an
implementation detail hidden behind `extractor.extract_context()`.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ModuleNode:
    """A single file/module in the dependency graph."""

    path: str  # repo-relative, forward-slash separated
    language: str
    loc: int = 0


@dataclass(frozen=True)
class DependencyEdge:
    """A directed "depends on" relationship between two modules."""

    source: str
    target: str


@dataclass(frozen=True)
class GraphStats:
    """Aggregate stats used for sizing/digest decisions."""

    file_count: int
    total_loc: int
    languages: dict[str, int] = field(default_factory=dict)  # language -> file count


@dataclass(frozen=True)
class GraphContext:
    """The structured knowledge graph consumed by prompt assembly."""

    modules: list[ModuleNode]
    edges: list[DependencyEdge]
    entry_points: list[str]
    stats: GraphStats
    source: str  # "graphifyy" | "native_fallback" | "cache"

    def fan_in_out(self) -> dict[str, int]:
        """Return {module_path: fan_in + fan_out} for hotspot ranking."""
        counts: dict[str, int] = {m.path: 0 for m in self.modules}
        for edge in self.edges:
            counts[edge.source] = counts.get(edge.source, 0) + 1
            counts[edge.target] = counts.get(edge.target, 0) + 1
        return counts

    def to_prompt_text(self, max_modules: int | None = None) -> str:
        """Render a compact, deterministic text summary for prompt injection."""
        modules = self.modules
        if max_modules is not None and len(modules) > max_modules:
            ranked = sorted(self.fan_in_out().items(), key=lambda kv: kv[1], reverse=True)
            keep = {path for path, _ in ranked[:max_modules]}
            modules = [m for m in modules if m.path in keep]
            kept_paths = {m.path for m in modules}
            edges = [e for e in self.edges if e.source in kept_paths and e.target in kept_paths]
            truncated_note = (
                f"\n(Digest truncated to the {max_modules} most-connected modules "
                f"out of {len(self.modules)} total.)\n"
            )
        else:
            edges = self.edges
            truncated_note = ""

        lines = [
            f"Source: {self.source}",
            f"Files: {self.stats.file_count}  Total LOC: {self.stats.total_loc}",
            f"Languages: {', '.join(f'{k}={v}' for k, v in self.stats.languages.items()) or 'unknown'}",
            f"Entry points: {', '.join(self.entry_points) or 'none detected'}",
            truncated_note,
            "Modules:",
        ]
        lines += [f"- {m.path} ({m.language}, {m.loc} LOC)" for m in modules]
        lines.append("Dependencies:")
        lines += [f"- {e.source} -> {e.target}" for e in edges]
        return "\n".join(line for line in lines if line)
