"""Context extraction: Graphifyy adapter + a dependency-free native fallback.

`extract_context()` is the single entry point the pipeline calls. It works
whether or not Graphifyy is installed:

1. If a cached result exists for the current repo content hash, use it.
2. Else, if `graphify` can be found (installed via `pip install scribe[graphifyy]`,
   or separately via `uv tool`/`pipx`), run it and parse/validate its output.
3. Else (or if Graphifyy's output fails validation), fall back to a native,
   dependency-free multi-language extractor so the tool never hard-fails
   just because Graphifyy isn't installed.

See docs/GRAPHIFYY_CONTRACT.md (repo root) for the expected Graphifyy
CLI/JSON contract -- treat it as a documented assumption, not a confirmed
spec, until reconciled against the real tool.
"""

from __future__ import annotations

import ast
import json
import os
import re
import shutil
import subprocess
import sys
from collections.abc import Callable
from enum import Enum
from pathlib import Path

from scribe.extraction.cache import (
    DEFAULT_CACHE_ROOT,
    compute_repo_hash,
    load_cached_context,
    store_cached_context,
)
from scribe.extraction.gitutil import list_tracked_files
from scribe.extraction.models import DependencyEdge, GraphContext, GraphStats, ModuleNode
from scribe.extraction.scan_config import SKIP_DIR_NAMES, iter_repo_files

# Extension -> coarse language label, used by the native fallback.
LANGUAGE_BY_EXTENSION = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".cs": "csharp",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".h": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".go": "go",
}

MAX_NATIVE_FILES = 4000
GRAPHIFYY_TIMEOUT_SECONDS = 120.0


class GraphifyyNotFoundError(RuntimeError):
    """Raised when the `graphifyy` executable cannot be located on PATH."""


class GraphifyyContractError(RuntimeError):
    """Raised when Graphifyy's output doesn't match the expected JSON contract."""


class GraphifyyMissingAction(Enum):
    """What to do when Graphifyy isn't installed, decided by an `on_graphifyy_missing` callback."""

    INSTALL_AND_RETRY = "install_and_retry"
    USE_FALLBACK = "use_fallback"


def manual_graphifyy_command(repo_path: Path) -> str:
    """The exact command a user can run themselves to reproduce/debug a Graphifyy run."""
    return f"graphify {repo_path} --no-viz --code-only"


def _install_graphifyy(status: Callable[[str], None]) -> bool:
    """Best-effort `pip install graphifyy` into the CURRENT interpreter's environment.

    Runs with output attached to the console (not captured) so the user sees pip's own
    progress during what can be a slow install (~25 tree-sitter grammars). Returns whether
    it succeeded; never raises -- a failed install is just another reason to fall back.
    """
    status("Installing graphifyy (pip install graphifyy)...")
    try:
        subprocess.run([sys.executable, "-m", "pip", "install", "graphifyy"], check=True, timeout=300)
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        status(f"Installing graphifyy failed ({exc}).")
        return False


def _find_graphify_executable() -> str | None:
    """Locate the `graphify` executable, preferring the current Python environment.

    `pip install scribe[graphifyy]` installs `graphify`'s console-script into the SAME
    environment as scribe -- but a plain `shutil.which()` only checks the OS `PATH`,
    which won't include that environment's `Scripts`/`bin` dir unless it was
    "activated" in the current shell. Scribe is frequently invoked via a direct
    interpreter path instead (e.g. `.venv\\Scripts\\python.exe -m scribe.cli`), so we
    check next to `sys.executable` first -- that's always correct regardless of
    activation state -- before falling back to a bare `PATH` lookup.
    """
    interpreter_dir = Path(sys.executable).parent
    candidate_names = ("graphify.exe", "graphify") if os.name == "nt" else ("graphify",)
    for name in candidate_names:
        candidate = interpreter_dir / name
        if candidate.exists():
            return str(candidate)
    return shutil.which("graphify")


def run_graphifyy(repo_path: Path, graphify_out_dir: Path, timeout: float = GRAPHIFYY_TIMEOUT_SECONDS) -> str:
    """Invoke the real `graphify` CLI (package `graphifyy`) and return its `graph.json` text.

    Note the executable is `graphify` (no trailing "y"), NOT `graphifyy` -- that's the PyPI
    package name, not the command on PATH. Output is written to files, not stdout; we redirect
    it to `graphify_out_dir` via the `GRAPHIFY_OUT` env var so nothing lands inside `repo_path`
    itself. Passes `--code-only`: scribe only wants the code knowledge graph, and without it
    Graphifyy's semantic pass over any docs/papers/images in the repo requires ITS OWN separate
    LLM API key (GEMINI_API_KEY/ANTHROPIC_API_KEY/etc.) -- a real failure mode discovered by
    actually running this against a repo containing a single markdown file. Raises
    `GraphifyyNotFoundError` if the executable isn't found, or
    `subprocess.TimeoutExpired`/`CalledProcessError` on failure. See docs/GRAPHIFYY_CONTRACT.md.
    """
    executable = _find_graphify_executable()
    if executable is None:
        raise GraphifyyNotFoundError(
            "`graphify` (package `graphifyy`) was not found. Install it with: pip install scribe[graphifyy]"
        )

    graphify_out_dir.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [executable, str(repo_path), "--no-viz", "--code-only"],
        capture_output=True,
        text=True,
        timeout=timeout,
        env={**os.environ, "GRAPHIFY_OUT": str(graphify_out_dir)},
    )
    if result.returncode != 0:
        raise subprocess.CalledProcessError(
            result.returncode, result.args, output=result.stdout, stderr=result.stderr
        )

    graph_json_path = graphify_out_dir / "graph.json"
    if not graph_json_path.exists():
        raise GraphifyyContractError(f"graphify exited successfully but {graph_json_path} was not created.")
    return graph_json_path.read_text(encoding="utf-8")


def parse_graphifyy_output(raw: str) -> GraphContext:
    """Parse and validate `graph.json` (NetworkX node-link format) into a `GraphContext`.

    Graphifyy's nodes are fine-grained concepts (functions, classes, doc sections), not files --
    we aggregate by `source_file` to fit our file-level `ModuleNode`/`DependencyEdge` model,
    which discards the `relation`/`confidence` detail on each link. See docs/GRAPHIFYY_CONTRACT.md.

    Raises `GraphifyyContractError` with an actionable message (including a snippet of the
    offending payload) on any schema mismatch, instead of letting a raw
    `KeyError`/`json.JSONDecodeError` bubble up.
    """
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        snippet = raw[:200].replace("\n", "\\n")
        raise GraphifyyContractError(
            f"graph.json was not valid JSON: {exc}. First 200 chars: {snippet!r}"
        ) from exc

    try:
        raw_nodes = payload["nodes"]
        raw_links = payload["links"]
        node_source_files = {n["id"]: n.get("source_file", "") for n in raw_nodes}
    except (KeyError, TypeError) as exc:
        snippet = json.dumps(payload)[:300]
        raise GraphifyyContractError(
            f"graph.json was valid JSON but missing expected keys ({exc}). "
            f"Payload snippet: {snippet}. See docs/GRAPHIFYY_CONTRACT.md for the expected shape."
        ) from exc

    languages: dict[str, int] = {}
    modules_by_file: dict[str, ModuleNode] = {}
    for source_file in node_source_files.values():
        if not source_file or source_file in modules_by_file:
            continue
        language = LANGUAGE_BY_EXTENSION.get(Path(source_file).suffix, "unknown")
        languages[language] = languages.get(language, 0) + 1
        modules_by_file[source_file] = ModuleNode(path=source_file, language=language, loc=0)

    edges: list[DependencyEdge] = []
    seen_edges: set[tuple[str, str]] = set()
    for link in raw_links:
        source_file = node_source_files.get(link.get("source"), "")
        target_file = node_source_files.get(link.get("target"), "")
        if not source_file or not target_file or source_file == target_file:
            continue
        pair = (source_file, target_file)
        if pair in seen_edges:
            continue
        seen_edges.add(pair)
        edges.append(DependencyEdge(source=source_file, target=target_file))

    stats = GraphStats(file_count=len(modules_by_file), total_loc=0, languages=languages)
    return GraphContext(
        modules=list(modules_by_file.values()),
        edges=edges,
        entry_points=[],
        stats=stats,
        source="graphifyy",
    )


# --------------------------------------------------------------------------
# Native, dependency-free fallback extractor (works with no Graphifyy at all)
# --------------------------------------------------------------------------

_IMPORT_PATTERNS = {
    "typescript": re.compile(
        r"""^\s*import\s+.*?from\s+['"](.+?)['"]|require\(['"](.+?)['"]\)""", re.MULTILINE
    ),
    "javascript": re.compile(
        r"""^\s*import\s+.*?from\s+['"](.+?)['"]|require\(['"](.+?)['"]\)""", re.MULTILINE
    ),
    "csharp": re.compile(r"^\s*using\s+([\w.]+)\s*;", re.MULTILINE),
    "cpp": re.compile(r'^\s*#include\s*[<"]([^>"]+)[>"]', re.MULTILINE),
    "java": re.compile(r"^\s*import\s+([\w.]+)\s*;", re.MULTILINE),
    "go": re.compile(r'^\s*import\s+\(?["]?([\w./]+)["]?', re.MULTILINE),
}


def _iter_source_files(repo_path: Path) -> list[Path]:
    """All files under `repo_path` with a recognized source extension, sorted."""
    return sorted(path for path in iter_repo_files(repo_path) if path.suffix in LANGUAGE_BY_EXTENSION)


def _extract_python_imports(text: str) -> list[str]:
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return []
    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imports.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports


def build_native_context(repo_path: Path, on_status: Callable[[str], None] | None = None) -> GraphContext:
    """Best-effort, dependency-free multi-language extractor.

    Produces a coarser graph than a real AST/knowledge-graph tool (Python
    gets real `ast`-based import resolution; other languages get a regex
    scan of import/using/include statements), but it means the pipeline
    never hard-requires Graphifyy to be installed.
    """
    modules: list[ModuleNode] = []
    edges: list[DependencyEdge] = []
    languages: dict[str, int] = {}
    total_loc = 0

    files = _iter_source_files(repo_path)
    if len(files) > MAX_NATIVE_FILES:
        if on_status:
            on_status(
                f"Native extractor found {len(files)} source files, over the "
                f"{MAX_NATIVE_FILES}-file cap; analyzing only the first {MAX_NATIVE_FILES} "
                "(sorted by path). Install Graphifyy for full coverage on repos this large."
            )
        files = files[:MAX_NATIVE_FILES]

    module_paths = {}  # stem -> repo-relative path, for resolving internal edges
    for path in files:
        rel_path = path.relative_to(repo_path).as_posix()
        module_paths[path.stem] = rel_path

    for path in files:
        rel_path = path.relative_to(repo_path).as_posix()
        language = LANGUAGE_BY_EXTENSION[path.suffix]
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        loc = text.count("\n") + 1
        total_loc += loc
        languages[language] = languages.get(language, 0) + 1
        modules.append(ModuleNode(path=rel_path, language=language, loc=loc))

        if language == "python":
            targets = _extract_python_imports(text)
        else:
            pattern = _IMPORT_PATTERNS.get(language)
            targets = []
            if pattern:
                for match in pattern.finditer(text):
                    targets.append(next(g for g in match.groups() if g))

        for target in targets:
            target_stem = target.split(".")[-1].split("/")[-1]
            resolved = module_paths.get(target_stem)
            if resolved and resolved != rel_path:
                edges.append(DependencyEdge(source=rel_path, target=resolved))

    entry_points = [
        m.path
        for m in modules
        if Path(m.path).name in {"main.py", "__main__.py", "index.ts", "index.js", "Program.cs"}
    ]

    stats = GraphStats(file_count=len(modules), total_loc=total_loc, languages=languages)
    return GraphContext(
        modules=modules, edges=edges, entry_points=entry_points, stats=stats, source="native_fallback"
    )


# --------------------------------------------------------------------------
# Orchestration
# --------------------------------------------------------------------------


def extract_context(
    repo_path: Path,
    *,
    use_cache: bool = True,
    refresh_cache: bool = False,
    force_native: bool = False,
    cache_dir: Path = DEFAULT_CACHE_ROOT,
    on_status: Callable[[str], None] | None = None,
    on_graphifyy_missing: Callable[[], GraphifyyMissingAction] | None = None,
    on_graphifyy_failed: Callable[[str, str], bool] | None = None,
) -> GraphContext:
    """Resolve a `GraphContext` for `repo_path` via cache -> Graphifyy -> native fallback.

    Cache files live under `cache_dir` (a user-level directory by default),
    not inside `repo_path` itself, so pointing this at a repo you don't own
    never leaves a `.scribe_cache/` directory behind in it. `graphify`'s own
    output (`graph.json`, `GRAPH_REPORT.md`) is likewise redirected under
    `cache_dir/graphify-out/` via the `GRAPHIFY_OUT` env var, for the same reason.

    `use_cache=False` skips both reading AND writing the cache for this run.
    `refresh_cache=True` skips reading (forces a fresh extraction) but still
    writes the result, so subsequent runs benefit from it.

    `on_graphifyy_missing` (called only if Graphifyy isn't found at all) decides whether to
    `pip install graphifyy` and retry, or fall back immediately -- if omitted, always falls
    back without asking (safe default for library/test callers). `on_graphifyy_failed` (called
    only when Graphifyy IS installed but a real run of it failed) is given the failure detail
    and the equivalent manual command, and returns whether to continue with the fallback
    (`True`) or abort so the user can investigate manually (`False`) -- if omitted, always
    continues.
    """

    def status(message: str) -> None:
        if on_status:
            on_status(message)

    repo_hash = compute_repo_hash(repo_path)

    if use_cache and not refresh_cache:
        cached = load_cached_context(repo_path, repo_hash, cache_root=cache_dir)
        if cached is not None:
            status("Using cached extraction result (repo content unchanged).")
            return cached

    context: GraphContext | None = None
    if not force_native:
        graphify_out_dir = cache_dir / "graphify-out"
        try:
            raw = run_graphifyy(repo_path, graphify_out_dir)
            context = parse_graphifyy_output(raw)
            status("Extracted via Graphifyy.")
        except GraphifyyNotFoundError:
            action = on_graphifyy_missing() if on_graphifyy_missing else GraphifyyMissingAction.USE_FALLBACK
            if action is GraphifyyMissingAction.INSTALL_AND_RETRY and _install_graphifyy(status):
                try:
                    raw = run_graphifyy(repo_path, graphify_out_dir)
                    context = parse_graphifyy_output(raw)
                    status("Extracted via Graphifyy.")
                except (
                    GraphifyyNotFoundError,
                    GraphifyyContractError,
                    subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                ) as exc:
                    status(f"Graphifyy install succeeded but extraction still failed ({exc}); falling back.")
            else:
                status("Continuing with the built-in native fallback extractor.")
        except subprocess.TimeoutExpired:
            detail = f"did not finish within {GRAPHIFYY_TIMEOUT_SECONDS:.0f}s"
            manual_command = manual_graphifyy_command(repo_path)
            if on_graphifyy_failed and not on_graphifyy_failed(detail, manual_command):
                raise
            status(f"Graphifyy {detail}; falling back to native extractor.")
        except (GraphifyyContractError, subprocess.CalledProcessError) as exc:
            detail = (
                exc.stderr.strip()
                if isinstance(exc, subprocess.CalledProcessError) and exc.stderr
                else str(exc)
            )
            manual_command = manual_graphifyy_command(repo_path)
            if on_graphifyy_failed and not on_graphifyy_failed(detail, manual_command):
                raise
            status(f"Graphifyy run failed ({detail}); falling back to native extractor.")

    if context is None:
        context = build_native_context(repo_path, on_status=on_status)
        status("Extracted via native fallback (coarser, dependency-free).")

    if use_cache:
        store_cached_context(repo_path, repo_hash, context, cache_root=cache_dir)

    return context


def build_project_context(repo_path: Path, max_lines: int = 200) -> str:
    """Depth-aware, size-capped textual directory tree for prompt orientation."""
    tracked = list_tracked_files(repo_path)
    tracked_set = set(tracked) if tracked is not None else None
    lines: list[str] = [f"Repository root: {repo_path.name}"]

    def walk(directory: Path, depth: int) -> None:
        if len(lines) >= max_lines or depth > 4:
            return
        try:
            entries = sorted(directory.iterdir(), key=lambda p: (p.is_file(), p.name))
        except OSError:
            return
        for entry in entries:
            if len(lines) >= max_lines:
                lines.append("... (truncated)")
                return
            if entry.name.startswith(".") or entry.name in SKIP_DIR_NAMES:
                continue
            if entry.is_symlink():
                continue
            if tracked_set is not None and entry.is_file():
                rel = entry.relative_to(repo_path).as_posix()
                if rel not in tracked_set:
                    continue
            indent = "  " * depth
            marker = "/" if entry.is_dir() else ""
            lines.append(f"{indent}- {entry.name}{marker}")
            if entry.is_dir():
                walk(entry, depth + 1)

    walk(repo_path, 0)
    return "\n".join(lines)
