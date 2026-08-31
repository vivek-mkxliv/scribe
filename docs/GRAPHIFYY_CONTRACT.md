# Graphifyy CLI/Output Contract — VERIFIED against the real tool 2026-08-24

Source: `Graphify-Labs/graphify` (PyPI package `graphifyy`, CLI executable `graphify`), read directly
from a local checkout. This replaces the earlier guessed contract, which was wrong on every count:
wrong executable name, wrong flags, wrong output channel, wrong JSON schema.

## Install & Executable Name

```bash
pip install scribe[graphifyy]   # recommended: installs into the SAME env as scribe
# or standalone: uv tool install graphifyy / pipx install graphifyy / pip install graphifyy
```

The **package** is `graphifyy` (double-y) but the **command on PATH is `graphify`** (single y, no
trailing letter). `shutil.which("graphifyy")` will never find it — must check for `graphify`.

`extractor._find_graphify_executable()` checks next to the running interpreter (`sys.executable`'s
directory) before falling back to a bare `shutil.which("graphify")` PATH lookup — verified necessary:
installing `graphifyy` into scribe's own venv does NOT put it on `PATH` unless that venv is
"activated" in the current shell, which scribe is frequently not (e.g. invoked via a direct
`.venv\Scripts\python.exe -m scribe.cli`). The interpreter-relative check works regardless.

## Invocation

Positional path argument, not `--path`/`--format` flags:

```bash
graphify <path> --no-viz --code-only
```

- `--no-viz` skips the (expensive, unused by us) HTML visualization — we only need `graph.json` +
  `GRAPH_REPORT.md`.
- **`--code-only` is required, not optional, for scribe's use case.** Verified by actually running
  Graphifyy against a repo containing a single non-code file: without it, Graphifyy's semantic
  pass over docs/papers/images demands its OWN separate LLM API key (`GEMINI_API_KEY`/
  `ANTHROPIC_API_KEY`/etc., independent of whatever key scribe itself is using) and fails hard
  without one. `--code-only` skips that pass entirely, using only local tree-sitter AST parsing —
  exactly the code knowledge graph scribe wants, no key, no cost, no extra failure mode.
- Exit code `0` on success. Progress/log output goes to stdout/stderr; on failure we now surface
  `stderr` in the fallback status message instead of just the generic "non-zero exit" text.
- **Output is written to files, not stdout.** Verified: when a path argument is given, output
  defaults to `<path>/graphify-out/`, not `<cwd>/graphify-out/` as the AI-agent-skill docs implied.
  We override this either way via the `GRAPHIFY_OUT` env var, pointed at our own cache directory so
  nothing is ever written inside the target repo.
- On a large corpus (>500 files or >2M words), the tool's *AI-agent skill* flow prompts interactively
  to narrow scope; the bare CLI's behavior on huge repos when invoked non-interactively is still not
  independently confirmed — mitigated by our existing subprocess timeout and native fallback on any
  failure/timeout.
- Useful flags for our use case: `--mode deep` (richer INFERRED edges, slower), `--update` (incremental
  re-extraction using its own cache), `--directed` (preserve edge direction).

## Output Files (under `GRAPHIFY_OUT` / `graphify-out/`)

| File | Contents |
|---|---|
| `graph.json` | The knowledge graph, NetworkX `node_link_data` format (see schema below). |
| `GRAPH_REPORT.md` | Human-readable summary: god nodes, detected communities, suggested questions. Worth injecting directly into the prompt as prose alongside the structured graph — arguably better digest material than reconstructing one from raw `graph.json` ourselves. |
| `graph.html` | Interactive viz — skipped via `--no-viz`, we don't consume it. |

## `graph.json` Schema (verified against `worked/httpx/graph.json` in the real repo)

```json
{
  "directed": false,
  "multigraph": false,
  "graph": {},
  "nodes": [
    {
      "id": "client_timeout_init",
      "label": ".__init__()",
      "file_type": "code",
      "source_file": "src/client.py",
      "source_location": "L17",
      "community": 1
    }
  ],
  "links": [
    {
      "source": "client",
      "target": "auth",
      "relation": "imports_from",
      "confidence": "EXTRACTED",
      "source_file": "src/client.py",
      "source_location": "L7",
      "weight": 1.0
    }
  ]
}
```

Key facts that broke our original assumption:
- The edge array key is **`links`**, not `edges` (standard NetworkX `node_link_data` default).
- Nodes are **concepts** (functions, classes, files, doc sections) — much finer-grained than our
  `ModuleNode` (one row per file). We aggregate by `source_file` to fit our model; this discards
  detail (per-function/class nodes, `confidence`/`relation` semantics) that a future revision of
  `GraphContext` could preserve directly for a richer prompt.
- `confidence` is `EXTRACTED` (explicit in source) / `INFERRED` (confidence_score 0.55-0.95) /
  `AMBIGUOUS` (flagged for human review) — we currently drop this signal when aggregating to
  file-level edges.
- No `entry_points` or `total_loc` equivalent exists in the schema at all — we leave these empty/zero
  on the Graphifyy path (only the native fallback computes real LOC).

## Failure Modes S.C.R.I.B.E. Handles

- `graphify` not on PATH → `GraphifyyNotFoundError` → silent fallback to native extractor.
- Subprocess exits non-zero, or times out → fallback to native extractor.
- `graphify-out/graph.json` missing after a successful exit, or JSON doesn't match the schema above
  (missing `nodes`/`links`, wrong types) → `GraphifyyContractError` → fallback to native extractor,
  with a snippet of the offending payload surfaced for debugging.

## Remaining Open Item

Whether the bare `graphify <path>` CLI (run non-interactively, no AI agent in the loop) silently
proceeds or hangs waiting for input on a >500-file / >2M-word corpus is not confirmed from reading
the source alone — the interactive narrowing behavior documented in `graphify/skill.md` is explicitly
written for an AI-agent-orchestrated flow, not necessarily the bare CLI. Our subprocess timeout +
native-fallback-on-any-failure already makes this safe either way, but it's worth an empirical test
against a genuinely large repo before fully trusting the Graphifyy path at scale.

