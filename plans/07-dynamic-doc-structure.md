# Plan 07 — Dynamic, Repo-Derived Documentation Structure

**Goal:** replace the fixed, hardcoded 4-doc/8-doc structure per `AudienceMode` with a documentation
*plan* (sections containing pages) that's derived from the actual repo -- sized to what's really
there, not a round number -- while still letting a user supply/compare their own structure.

## Motivation

The prior structure (`constants.DOC_SUITE`) generated exactly one flat file per doc id (e.g.
`USER_GUIDES.md` as a single monolithic document), regardless of repo size or shape. A real
documentation space (see the Confluence-style example that prompted this plan) is a *tree*:
top-level sections that each contain several pages (e.g. "User Guides" containing one page per
workflow/entry point). This plan makes that the default behavior, derived per-repo instead of
templated.

## Design

- **`generation/doc_plan.py`** -- `DocPage`/`DocSection`/`DocPlan` dataclasses. `DocPlan.doc_ids`
  is the flattened, ordered list of page ids (which may include a folder prefix, e.g.
  `"user-guides/01-gui.md"`) that `writer`/`manifest` already consume as opaque strings -- no
  changes needed to the marker-based parsing/validation contract from Plan 02.
- **Two ways to get a plan**:
  1. `derive_doc_plan_via_llm` -- a dedicated planning LLM call (new `templates/planning_prompt.md`)
     that returns strict JSON, grounded in the real `GraphContext` (entry points, languages,
     module count). Retries once on a malformed response, then falls back to...
  2. `heuristic_doc_plan` -- a zero-cost, deterministic structure wrapping the old fixed
     `DOC_SUITE` list in one section. Used for `--dry-run` (which must never make a real LLM
     call) and as the last-resort fallback if the LLM planner still fails after a retry.
- **Caching ("memory storage")**: the derived plan is cached per `(repo_hash, mode)` under
  `cache_dir/doc_plans/`, exactly like extraction caching -- an unchanged repo never re-derives
  it. `--refresh-plan` forces a fresh derivation.
- **User input + reconciliation**: `--doc-plan-file <path>` points at a user-authored JSON plan
  (e.g. a hand-edited `.scribe_plan.json` from a prior run). `reconcile_doc_plan` compares it
  against the recommended plan: identical -> use it without asking; different -> ask
  interactively (`_confirm_doc_plan_conflict` in `cli.py`, gated the same way as the Graphifyy
  install/failure prompts -- never fires under `--quiet`/`--yes`/non-TTY) which one to use,
  defaulting to the user's explicit file when running non-interactively.
- **Persistence for quick reference**: the finalized plan (including its `rationale`) is written
  to `output_dir/.scribe_plan.json` every real run, both as a human-readable artifact and as
  something a user can copy, hand-edit, and pass back via `--doc-plan-file` next time.
- **Nested output**: `writer.write_documents` now creates the parent directory for any doc id
  with a folder prefix -- a one-line, backward-compatible addition (a flat id's "parent" is just
  `output_dir` itself).
- **Cost-confirmation ordering**: the token-budget/chunking-need estimate (and any resulting
  `CostConfirmationRequiredError`) uses the heuristic plan, not the real derived one -- so
  declining a cost confirmation never pays for a planning call it didn't need. The real plan
  (cached-or-LLM-derived) is only resolved once the run is confirmed to proceed.

## Tasks

- [x] **7.1** `generation/doc_plan.py`: `DocPage`/`DocSection`/`DocPlan`, JSON (de)serialization,
  `to_prompt_text()`, `heuristic_doc_plan`, `derive_doc_plan_via_llm` (with one retry + fallback),
  `reconcile_doc_plan`, `load_user_doc_plan`, `load_cached_doc_plan`/`store_cached_doc_plan`.
- [x] **7.2** `templates/planning_prompt.md`: dedicated structure-planning prompt, grounded in
  the real `GraphContext`, explicit instruction to size sections/pages from real signals, not a
  round number.
- [x] **7.3** `templates/master_prompt.md` + `generation/prompt_builder.py`: drop the hardcoded
  "IF audience_mode is X: docs 1-8..." block; render `{doc_plan}` (the finalized plan's
  `to_prompt_text()`) and `{audience_guidance}` (moved to `constants.AUDIENCE_MODE_GUIDANCE`)
  instead.
- [x] **7.4** `generation/writer.py`: `write_documents` creates nested parent directories;
  removed the now-unused `write_docs(markdown, output_dir, mode)` convenience wrapper (dead code,
  hardcoded to the old fixed `DOC_SUITE` shape).
- [x] **7.5** `config.py`: added `doc_plan_file: Path | None` and `refresh_plan: bool` to
  `ScribeConfig`.
- [x] **7.6** `pipeline.py`: `_resolve_doc_plan()` resolves cached-or-derived-or-fallback plan,
  reconciles against `config.doc_plan_file`, persists `.scribe_plan.json`. `run()` rewired so
  `expected_doc_ids` everywhere comes from the finalized `DocPlan`, not `DOC_SUITE[config.mode]`
  directly. Incremental-skip shortcut bypassed when `--doc-plan-file`/`--refresh-plan` is set.
- [x] **7.7** `cli.py`: `--doc-plan-file`/`--refresh-plan` options; `_confirm_doc_plan_conflict`
  interactive callback, wired into `_run_with_confirmations` the same way as the Graphifyy
  install/failure callbacks; `DocPlanContractError` added to the generation-failure exception
  handling.
- [x] **7.8** Tests: `tests/test_doc_plan.py` (19 new tests -- JSON round-trip, validation
  rejections, heuristic fallback, LLM-derivation success/retry/fallback, reconciliation in all
  three shapes, user-plan-file loading, cache round-trip/miss); `tests/test_writer.py` (nested
  doc id -> nested directory); updated `tests/test_pipeline_cost.py` and
  `tests/test_pipeline_incremental.py`'s `FakeLLMClient`s to answer the new planning call and
  adjusted call-count assertions accordingly. 104/104 tests passing, `ruff check`/`ruff format
  --check`/`mypy` all clean.

## Deliberately Deferred (not in this pass)

- `--doc-plan-file`/`--refresh-plan` are not yet wired into `scribe.toml`/`[tool.scribe]` project
  config (`project/config_loader.py`'s `CONFIG_FIELDS`) -- CLI-flag-only for now, consistent with
  "avoid flag proliferation until there's a real need."
- The manifest (`.scribe_manifest.json`) doesn't track a plan hash; a `--doc-plan-file` run
  simply bypasses the incremental-skip shortcut unconditionally rather than comparing hashes.
  Simpler, and sufficient since supplying that flag is already a deliberate, infrequent action.
- No live end-to-end verification against a real LLM yet -- same standing gap named in
  `audit_reports/` for the rest of the pipeline. The planning call is architected and unit-tested
  against scripted responses (consistent with how every other LLM-touching stage in this codebase
  is tested), but has not been observed against a real model's actual output.

## Acceptance Criteria

- A repo with two distinct entry points can produce a plan with 2+ pages under one section instead
  of being forced into a single flat file, when the LLM planner determines that's warranted.
- `--dry-run` still makes zero LLM calls (verified: uses `heuristic_doc_plan`, never touches
  `llm_client.build_client`).
- Re-running `scribe generate` on an unchanged repo re-derives neither the graph nor the doc plan.
- A user-supplied `--doc-plan-file` identical to the recommended plan never prompts; a differing
  one prompts interactively (or defaults to the user's file under `--quiet`/`--yes`/non-TTY).
