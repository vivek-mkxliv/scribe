"""Chunked/map-reduce context digesting for repos too large for one prompt.

When even the smallest graph digest (see `models.GraphContext.to_prompt_text`)
would blow the token budget, summarizing every module in one call stops
scaling. Instead: group modules by top-level package, ask the LLM for a
short summary of each package's internal structure (map), then concatenate
those summaries into the "digest" text handed to the real doc-generation
prompt (reduce) via `prompt_builder.build_prompt_with_digest_text`.
"""

from __future__ import annotations

from collections.abc import Callable

from scribe.extraction.models import GraphContext, GraphStats
from scribe.providers.llm_client import LLMClient

_SUMMARY_PROMPT_TEMPLATE = """You are analyzing one subsystem of a larger codebase for a \
documentation generator.
Summarize this subsystem's purpose and internal structure in 3-6 sentences, suitable for feeding into
a larger architecture document. Be concrete: name the key modules and what they depend on.

Subsystem: {package_name}

{package_digest}
"""


def group_modules_by_package(graph_context: GraphContext) -> dict[str, GraphContext]:
    """Partition `graph_context` into one sub-`GraphContext` per top-level path segment.

    A module with no directory component (e.g. `main.py`) is grouped under `"(root)"`.
    Edges are kept only when both endpoints fall in the same package; cross-package
    edges are dropped here since they'd need a global (non-chunked) view to render sensibly.
    """
    package_of: dict[str, str] = {}
    for module in graph_context.modules:
        parts = module.path.split("/")
        package_of[module.path] = parts[0] if len(parts) > 1 else "(root)"

    packages: dict[str, list] = {}
    for module in graph_context.modules:
        packages.setdefault(package_of[module.path], []).append(module)

    sub_contexts: dict[str, GraphContext] = {}
    for package_name, modules in packages.items():
        module_paths = {m.path for m in modules}
        edges = [e for e in graph_context.edges if e.source in module_paths and e.target in module_paths]
        languages: dict[str, int] = {}
        for m in modules:
            languages[m.language] = languages.get(m.language, 0) + 1
        stats = GraphStats(
            file_count=len(modules), total_loc=sum(m.loc for m in modules), languages=languages
        )
        sub_contexts[package_name] = GraphContext(
            modules=modules, edges=edges, entry_points=[], stats=stats, source=graph_context.source
        )

    return sub_contexts


def build_chunked_digest(
    client: LLMClient,
    model: str,
    graph_context: GraphContext,
    on_status: Callable[[str], None] | None = None,
) -> str:
    """Map-reduce a `GraphContext` too large for one prompt into a single digest string.

    Makes one small LLM call per top-level package (map), then concatenates the
    summaries (reduce). The returned text replaces `GraphContext.to_prompt_text()`
    as the `{graphifyy_context}` slot in the master prompt.
    """

    def status(message: str) -> None:
        if on_status:
            on_status(message)

    packages = group_modules_by_package(graph_context)
    status(f"Repo digest too large for one call; summarizing {len(packages)} package(s) individually.")

    summaries: list[str] = [
        f"Overall: {graph_context.stats.file_count} files across {len(packages)} top-level packages.",
    ]
    for package_name, sub_context in sorted(packages.items()):
        prompt = _SUMMARY_PROMPT_TEMPLATE.format(
            package_name=package_name, package_digest=sub_context.to_prompt_text()
        )
        summary = client.complete(prompt, model)
        summaries.append(f"### Package: {package_name}\n{summary.strip()}")
        status(f"Summarized package '{package_name}'.")

    return "\n\n".join(summaries)
