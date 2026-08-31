# Plan 01 — Context Extraction Engine

**Goal:** make Graphifyy integration a real, validated, cacheable contract instead of a shell-out-and-pray call, and give the tool a way to function (degraded) when Graphifyy isn't installed.

## Current State

[`src/scribe/extraction/extractor.py`](../src/scribe/extraction/extractor.py) *(moved from `core/extractor.py`)* does two things:

- `run_graphifyy()` shells out to a `graphifyy` executable with guessed flags (`--path`, `--format json`), returns raw stdout as an opaque string, and never parses or validates it. If Graphifyy's real CLI contract differs even slightly, this fails or silently sends garbage to the LLM.
- `build_project_context()` is a one-level `os.listdir` — no recursion, no size awareness, no signal about what's actually important in the repo.

There is no caching (Graphifyy reruns on every invocation even if nothing changed), no fallback for repos/machines without Graphifyy installed, and no strategy for graphs too large to fit in an LLM context window.

## Goals

1. Define an explicit, versioned data contract for what "graph context" means inside S.C.R.I.B.E., independent of Graphifyy's actual CLI.
2. Validate Graphifyy's output against that contract and fail with an actionable error, not a stack trace.
3. Cache extraction results keyed by content hash so re-runs on an unchanged repo are instant.
4. Provide a native Python-AST fallback extractor so the tool still produces *something* useful without Graphifyy installed.
5. Summarize/compress the graph when it's too large for the target model's context window, instead of dumping it all into the prompt.

## Tasks

- [x] **1.1** Add `src/scribe/extraction/models.py` *(moved from `core/models.py`)* with a `GraphContext` dataclass: `modules: list[ModuleNode]`, `edges: list[DependencyEdge]`, `entry_points: list[str]`, `stats: GraphStats` (file count, LOC, language breakdown). This is what the rest of the pipeline consumes — never raw Graphifyy stdout.
- [x] **1.2** Write `parse_graphifyy_output(raw: str) -> GraphContext` in `extractor.py`. Validate required JSON keys exist; raise `GraphifyyContractError` with the offending payload snippet on mismatch (don't let a `KeyError`/`json.JSONDecodeError` bubble up raw). *(Rewritten against the real NetworkX node-link `graph.json` schema — see 1.3.)*
- [x] **1.3** Document the exact CLI invocation and JSON schema S.C.R.I.B.E. expects from Graphifyy in `docs/GRAPHIFYY_CONTRACT.md` *(moved from `src/scribe/core/GRAPHIFYY_CONTRACT.md`)*, including a minimal example payload. *(VERIFIED against the real `Graphify-Labs/graphify` source and a real sample `graph.json`, not just an assumption anymore. Corrected: the executable is `graphify`, not `graphifyy`; invocation is positional (`graphify <path> --no-viz`), not `--path`/`--format`; output is written to files (`graph.json`, `GRAPH_REPORT.md`), not stdout; the edge array key is `links`, not `edges`; nodes are fine-grained concepts, not files — we aggregate by `source_file`.)*
- [x] **1.4** Add content-hash caching: hash tracked file contents (`git ls-files` + mtime/sha fallback for non-git dirs) into a cache key, store `GraphContext` as JSON under a user-level cache dir, skip re-running Graphifyy on cache hit. `--no-cache` (skip read+write) and `--refresh-cache` (skip read, still write) are both implemented as distinct flags, plus `--force-native-extractor`.
- [x] **1.5** Implement `NativeAstExtractor` (Python-only fallback) using the stdlib `ast` module: walk `*.py` files, build a coarse import graph (module → imported modules) as a `GraphContext`. Auto-select this when `graphifyy` isn't on PATH, with a clear `console.print` warning that output quality will be reduced. *(Shipped as `build_native_context`, extended beyond Python-only to a regex-based scan for TS/JS/C#/C++/Java/Go too.)*
- [x] **1.6** Add a **graph digest** step: when `GraphContext` serializes to more tokens than a configurable budget (default derived from `--model`'s known context window), collapse it to package-level granularity (drop per-function detail, keep module/package edges and hotspot rankings by fan-in/fan-out) before it reaches the prompt builder. *(Implemented via `GraphContext.to_prompt_text(max_modules=...)` + `pipeline._build_bounded_prompt` progressively shrinking the digest to fit `--token-budget`.)*
- [x] **1.7** Replace `build_project_context`'s flat `os.listdir` with a depth-limited recursive tree (respect `.gitignore` via `git ls-files` when available; otherwise skip common noise dirs) capped at a line budget, so large repos don't blow the prompt on directory listings alone.
- [x] **1.8** Update `pipeline.run()` to consume `GraphContext` objects, not strings, and to call the cache lookup before invoking Graphifyy or the native fallback.
- [x] **1.9** Unit tests: tests for `parse_graphifyy_output` (valid real-schema payload + malformed/invalid-JSON payloads), cache hit/miss/invalidation, `--refresh-cache` read/write decoupling, native fallback correctness (Python/C#/Unreal-Unity noise-dir skipping/file-cap truncation), digest collapsing above/below budget. *(`tests/test_extractor.py`, `tests/test_models.py` — inline `tmp_path` fixtures rather than a checked-in `tests/fixtures/sample_repo/`, which is a reasonable simplification, not a gap.)*

## Acceptance Criteria

- Running `scribe generate` twice in a row on an unchanged repo skips Graphifyy entirely on the second run (visibly, via a status message).
- Uninstalling `graphify` from PATH does not crash the tool — it falls back and warns.
- A malformed/unexpected Graphifyy payload produces a one-line, human-readable error, never a raw traceback.
- A synthetic 500-module repo does not exceed the configured token budget in the assembled prompt.

## Resolved: Former Open Risk

Graphifyy's real CLI/JSON contract has been confirmed by reading the actual `Graphify-Labs/graphify` source
(package `graphifyy`, CLI `graphify`) and a real sample `graph.json` from its own `worked/` examples.
See `docs/GRAPHIFYY_CONTRACT.md` for the full verified contract. One residual, lower-stakes
unknown remains: whether the bare `graphify <path>` CLI (invoked non-interactively, no AI agent in the
loop) behaves identically to the AI-agent-orchestrated flow on a >500-file/>2M-word corpus, or could
block waiting for input — not independently confirmed from the source, mitigated regardless by our
existing subprocess timeout + native-fallback-on-any-failure.

**Update 2026-08-25:** `graphifyy` (0.9.48) is now actually `pip install`ed into this project's own
dev environment, so `_find_graphify_executable()` resolves a real binary here. A `graphify-out/`
directory exists under the real user-level cache (`~/.scribe_cache`), but it's currently empty, so
this re-audit can't independently confirm a fresh, real end-to-end `graphify` subprocess run beyond
what was already verified in the prior session (real sample `graph.json` parsing, real CLI contract
reading). Treat "graphify runs correctly against an arbitrary large repo on this machine" as still
unconfirmed by this session, distinct from "the contract is documented correctly" (which is confirmed).

- [x] **1.10** *(Added 2026-08-25)* Distinguish "Graphifyy not installed" from "Graphifyy installed but
  a real run failed" and handle each with a different interactive recovery path, instead of treating
  both as one generic fallback trigger. Implemented via two new optional callbacks threaded through
  `extract_context()` -> `pipeline.run()` -> `cli.py`: `on_graphifyy_missing` (offers `pip install
  graphifyy` then a single retry, or immediate fallback) and `on_graphifyy_failed` (shows the failure
  detail plus the exact manual `graphify ...` command, then asks whether to continue with the native
  fallback or abort so the user can investigate). Both are only wired up when the CLI run is
  interactive (`not --quiet`, not `--yes`, `sys.stdin.isatty()`) so `--quiet`/`--yes`/CI/non-TTY runs
  keep the old silent-fallback behavior and never hang. *(`extraction/extractor.py`'s
  `GraphifyyMissingAction` enum + `_install_graphifyy()`, `pipeline.py`, `cli.py`'s
  `_confirm_graphifyy_missing`/`_confirm_graphifyy_failed`; 5 new tests in `tests/test_extractor.py`
  covering install-and-retry, declined-install fallback, failed-run continue, and failed-run abort.)*
