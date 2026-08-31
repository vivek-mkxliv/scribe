# Plan 04 — Quality Gates, Testing & Drift Enforcement

**Goal:** give the project a real safety net — unit/integration tests, CI, linting, and a CI-friendly way to guarantee docs never silently go stale.

## Current State

There is no `tests/` directory, no CI workflow, no linter/type-checker configuration, and no automated way to know if a change to `pipeline.py`, `writer.py`, or the prompt template breaks generation. `scribe generate --check` (from Plan 03) is designed but not yet enforced anywhere.

## Goals

1. Establish a pytest suite covering every core module with mocked external dependencies (no real LLM/Graphifyy calls in CI).
2. Add linting/type-checking so regressions are caught before runtime.
3. Add a GitHub Actions workflow that runs tests + lint on every PR.
4. Add a CI job that runs `scribe generate --check` against this very repo so S.C.R.I.B.E.'s own docs can never silently drift.

## Tasks

- [x] **4.1** Create `tests/` covering the core modules. *(Flat `tests/` instead of the originally proposed `tests/core/` mirror — 12 files, 85 tests total as of 2026-08-25. No checked-in `tests/fixtures/` sample repo yet; fixtures are built inline via `tmp_path` per test instead. No `test_prompt_builder.py` or a dedicated `test_llm_client.py` yet.)*
- [x] **4.2** Add a `FakeLLMClient` test double (implements the `LLMClient` protocol) so `pipeline`/`writer` tests never hit a real API — scriptable to return well-formed, malformed, or partially-missing marker output to exercise Plan 02's repair loop. *(`tests/test_pipeline_repair.py`.)*
- [ ] **4.3** Add `pytest-cov`; set a minimum coverage threshold (start realistic, e.g. 70%, ratchet up over time) enforced in CI.
- [~] **4.4** Add `ruff` (lint + format) and `mypy` (or `pyright`) configuration in `pyproject.toml`; fix existing violations across the current codebase as a baseline commit. *(Updated 2026-08-25: `[tool.ruff]` (`line-length = 110`) and `[tool.ruff.lint]` (`select = ["E", "F", "I", "UP", "B", "C4", "SIM"]`) are now present in `pyproject.toml` and enforced -- `ruff check`/`ruff format --check` both pass clean. `mypy` is still run on tool defaults only; no `[tool.mypy]` config block exists yet, so this task is not fully closed.)*
- [ ] **4.9** *(Added 2026-08-25)* Fix `tests/test_cli.py` so `CliRunner` invocations of `generate` pass an isolated `--cache-dir` (or an autouse fixture patches `DEFAULT_CACHE_ROOT`) instead of hitting the real, default `~/.scribe_cache` -- confirmed during this audit that the real user-level cache directory on this machine contains dozens of near-empty entries that can only have come from test runs. Do this before 4.5's CI matrix lands, so CI runners don't silently accumulate test artifacts in a shared/cached environment.
- [ ] **4.5** Add `.github/workflows/ci.yml`: matrix over supported Python versions, steps for `pip install -e .[dev]`, `ruff check`, `mypy`, `pytest --cov`.
- [ ] **4.6** Add a second CI job (or step) that runs `scribe generate --check` against this repository itself using a previously-committed manifest, failing the build if the checked-in docs are stale relative to source changes in the PR. This is the concrete proof the "docs never go stale" promise holds. *(Blocked on Plan 03 tasks 3.6/3.7 — `--check`/manifest don't exist yet.)*
- [ ] **4.7** Add `pre-commit` config (`ruff`, `mypy`, optionally `scribe generate --check`) so issues are caught before push, not just in CI.
- [ ] **4.8** Document how to run the full quality suite locally in `CONTRIBUTING.md` (paired with Plan 06). *(`CONTRIBUTING.md` doesn't exist yet — blocked on Plan 06 task 6.3.)*

## Acceptance Criteria

- `pytest` passes with zero network/subprocess calls to real LLM providers or a real `graphifyy` binary.
- CI fails on lint, type, or test regressions before merge.
- A PR that changes source code without updating generated docs fails the drift-check CI job.
- Coverage threshold is enforced, not just reported.
