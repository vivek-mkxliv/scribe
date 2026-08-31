# Plan 03 — CLI & Developer Experience Overhaul

**Goal:** make S.C.R.I.B.E. feel like a polished product, not a script — config persistence, a guided first run, visible progress, and the flagship differentiator: incremental, diff-aware regeneration.

## Current State

[`src/scribe/cli.py`](../src/scribe/cli.py) is a single `generate` command with flags only — every invocation re-specifies `--mode`, `--repo`, `--provider`, `--model`. There's no config file, no interactive setup, no progress indication during what can be a multi-minute LLM call (the user just sees a static "generating..." line), a broad `except Exception` that can mask real bugs as generic "Generation failed" messages, no overwrite confirmation before clobbering an existing `/docs` folder, and no way to regenerate only what changed.

## Goals

1. Let a team set project defaults once (`scribe.toml` or `[tool.scribe]` in `pyproject.toml`) instead of retyping flags.
2. Add `scribe init` — a guided first-run wizard.
3. Add real progress feedback (spinners/steps) for extraction and generation phases.
4. Add incremental regeneration: only touch the docs affected by what changed since the last run.
5. Prevent accidental data loss (overwriting hand-edited docs) without nagging on every run.

## Tasks

- [x] **3.1** Add `project/config_loader.py` (moved from `core/project_config.py`): load `[tool.scribe]` from `pyproject.toml` if present, else `scribe.toml` in repo root. Precedence: CLI flag > config file > built-in default. Fields mirror `ScribeConfig`: `mode`, `provider`, `model`, `output_dir`, `max_repair_attempts`, `chunked`, etc. *(`scribe.toml` takes precedence over `pyproject.toml` if both exist; CLI flags detected as explicitly-passed via `ctx.get_parameter_source`.)*
- [x] **3.2** Add `scribe init` command: interactively asks (via `click.prompt`) for mode, provider, output dir; writes the answers to `scribe.toml`; detects and reports whether `graphify` is on PATH and whether the chosen provider's API key env var is already set.
- [x] **3.3** Add `rich.status` around each pipeline phase, replacing the single static print. *(Three verbosity levels: default single updating status line, `--verbose` prints every status message on its own line, `--quiet` suppresses them. Token-level streaming remains deferred to Plan 02's still-open streaming item, not duplicated here.)*
- [x] **3.4** Narrow the current blanket `except Exception` in `generate()` to catch specific known exceptions with tailored messages. *(Verified: no bare `except Exception` exists in `cli.py` -- it already caught `GraphifyyNotFoundError`/`GraphifyyContractError`/`UnsupportedProviderError`/`ValueError`/`DocumentCountMismatchError`/`GenerationFailedError`/`CostConfirmationRequiredError` from earlier work; `OverwriteConfirmationRequiredError` added to the same pattern.)*
- [x] **3.5** Add `--yes`/`-y` flag (reusing the flag already added for cost confirmation in Plan 02, rather than a separate `--force`, to avoid flag proliferation); without it, if `output_dir` contains files scribe doesn't already own (no `.scribe_manifest.json`), raise `OverwriteConfirmationRequiredError` and the CLI confirms before overwriting. *(Deliberately does NOT re-prompt on every regeneration once a manifest exists -- only for files scribe doesn't recognize as its own, per the plan's own goal of "without nagging on every run." No `rich`-based diff-summary of which files will change; only a filename list.)*
- [x] **3.6** Implement incremental regeneration: `.scribe_manifest.json` (`project/manifest.py`, moved from `core/manifest.py`) records the repo content hash + mode + doc ids from the last successful run. `--incremental/--no-incremental` (default: incremental on) skips the whole pipeline -- no extraction, no LLM call -- when the hash/mode still match.
- [x] **3.7** Add `scribe generate --check` (drift-check mode): compares the current repo hash against the manifest, exits non-zero if stale or never generated -- no extraction, no LLM call, CI-safe. *(`pipeline.check_drift`.)*
- [x] **3.8** Add `--verbose`/`--quiet` global flags. *(Implemented as console-output verbosity control via `_make_status_reporter` in `cli.py`, not the stdlib `logging` module as originally proposed -- a deliberate simplification consistent with the existing `on_status` callback architecture; achieves the same user-facing behavior.)*
- [x] **3.9** Tests: `click.testing.CliRunner` coverage for `init` (+ its output being picked up by `generate`), `generate --check` (both stale-with-no-manifest and the relative-output-dir-from-config-file regression), plus pipeline-level tests for incremental skip/regeneration and overwrite confirmation (`tests/test_manifest.py`, `tests/test_project_config.py`, `tests/test_pipeline_incremental.py`, `tests/test_cli.py`).
- [x] **3.10** *(Added 2026-08-25, cross-referenced from Plan 01 task 1.10)* `_run_with_confirmations()` now derives an `interactive` flag (`not --quiet and not --yes and sys.stdin.isatty()`) and only wires up the new `on_graphifyy_missing`/`on_graphifyy_failed` prompts when true, consistent with the existing cost/overwrite confirmation pattern -- `--quiet`/`--yes`/CI/non-TTY behavior is unchanged (silent fallback, never hangs). `generate()`'s exception handling was extended to also catch `subprocess.CalledProcessError`/`subprocess.TimeoutExpired` so declining to continue after a real Graphifyy failure aborts cleanly instead of a raw traceback.

> **Note on test-fixture hygiene (found during the 2026-08-25 re-audit):** `tests/test_cli.py`'s `CliRunner` invocations of `generate` don't pass `--cache-dir`, so they exercise the real, default `~/.scribe_cache` on whatever machine runs them, rather than an isolated `tmp_path`. This was confirmed by inspecting the real cache directory on this machine: dozens of near-empty (`file_count: 0`) cached contexts that can only have come from test runs, not real usage. Not a correctness bug in the product itself, but it means every CI/dev machine's real cache directory gets test pollution. Worth fixing (an autouse fixture forcing an isolated `cache_dir`) before Plan 04's CI matrix lands, so CI runners don't accumulate stale test artifacts run over run.

## Acceptance Criteria

- A fresh clone can run `scribe init` then `scribe generate` with zero additional flags and get sensible output.
- Re-running `scribe generate` on an untouched repo with `--incremental` (default) completes in under a second and makes no LLM calls.
- `scribe generate --check` can be dropped straight into a CI job and produces a non-zero exit code on stale docs.
- No `except Exception` blocks remain that would mask a genuine bug as a generic user-facing error.
