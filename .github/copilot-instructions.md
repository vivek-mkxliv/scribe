# S.C.R.I.B.E. — Project Guidelines

System Context & Repository Intelligence Bridge Engine: a Python CLI that generates multi-tiered,
audience-aware documentation suites from a Graphifyy-derived (or native-fallback) knowledge graph
of a codebase. Meant to be a long-term maintenance tool (incremental regeneration, drift-checking)
— not a one-shot generator. See [plans/README.md](../plans/README.md) for the original feature
roadmap and [README.md](../README.md) for user-facing usage.

## Build and Test

Always use the project venv's interpreter explicitly — `python`/`py` alone may not resolve to it:

```powershell
& "<repo>/.venv/Scripts/python.exe" -m ruff format .
& "<repo>/.venv/Scripts/python.exe" -m ruff check .
& "<repo>/.venv/Scripts/python.exe" -m mypy src/scribe --ignore-missing-imports
& "<repo>/.venv/Scripts/python.exe" -m pytest -q
```

Run all four, in this order, after any change. `ruff format` does not break long f-strings/lines
on its own — fix an E501 it leaves behind manually (split into a parenthesized concatenation).
Line length is 110 (`[tool.ruff]` in `pyproject.toml`), not the default 88/120.

## Architecture

Pipeline (`src/scribe/pipeline.py`, the orchestrator), in order:
1. **Context extraction** (`extraction/extractor.py`) — Graphifyy or native fallback → `GraphContext`.
2. **Doc plan resolution** (`generation/doc_plan.py`) — durable `.scribe_plan.json` → user-level
   cache → one LLM planning call as last resort. Structure (sections/pages) is repo-derived, not a
   fixed list — `constants.DOC_SUITE` is now only the zero-cost `--dry-run`/failure fallback.
3. **Per-page staleness partition** — skips pages whose grounding sources haven't changed.
4. **Per-page generation** (`generation/page_writer.py`) — one LLM call per page, with a
   repair-loop, truncation-continuation/escalation, and placeholder fallback so one bad page never
   fails the whole run.
5. **Write + manifest** (`generation/writer.py`, `project/manifest.py`).

`scribe revise-plan REQUEST` is a separate on-demand entry point for structure-only revisions.

### Persistence layers — meant to be committed to version control, NOT gitignored
- `.scribe_plan.json` — structure (what).
- `.scribe_manifest.json` — staleness state (repo hash, page hashes).
- `scribe-doc-suite-justification.md` — why (rationale + dated revision history).
- `scribe.notes.md` / `scribe.org.toml` — optional, hand-authored, never auto-overwritten.
- `scribe.presets.json` — optional, named reusable configurations (`project/presets.py`); unlike
  the others this one CAN be machine-written (by `scribe gui`/`scribe tui`), which is why it's
  JSON, not TOML (`tomllib` is read-only). Never stores a raw API key, only `api_key_env`.

## GUI / TUI (see [plans/08-gui-and-presets.md](../plans/08-gui-and-presets.md) for full detail)

Two UI surfaces on top of the same `pipeline.run()`, both launched only via an explicit command
(never on bare `scribe`):
- `scribe gui` — local browser UI (`src/scribe/gui/server.py` + `static/index.html`), stdlib
  `http.server`/`webbrowser` only, zero extra dependencies, bound to `127.0.0.1`.
- `scribe tui` — Textual TUI (`src/scribe/gui/tui.py`), opt-in via the `tui` extra
  (`pip install scribe[tui]`); the browser UI needs no extra install at all.
- `src/scribe/gui/app.py` is the framework-agnostic core (`resolve_form_defaults`,
  `build_config`, `RunState`/`run_generation`) shared by the browser server; the TUI reuses
  `resolve_form_defaults`/`build_config` but calls `pipeline.run()` directly in its own worker
  (no HTTP boundary to poll around).
- `src/scribe/gui/tui_ptg.py` is an **experimental, unwired** second TUI prototype (pytermgui)
  kept only for comparison against Textual — not exposed as a CLI command; ignore it unless
  asked to work on the TUI-framework decision specifically.

## Fail-Safe Design Principle (core philosophy — honor this in every change)

Staleness/caching/QA must default to "regenerate" / "treat as unavailable" / "flag it" whenever a
signal is missing or ambiguous — never silently skip or invent on uncertain grounds. Every new
schema field needs a safe default so old cached plans/manifests degrade gracefully instead of
erroring.

## Anti-Hallucination Guardrails (2026-09-04 — apply to any prompt template change)

This is a code-to-documentation tool: a confidently wrong command/flag/fact is worse than none.
`src/scribe/templates/*.md` encode hard rules for generated content — never weaken these when
editing a template: ground every concrete claim in the real Project Context/Knowledge
Graph/Detected CLI Surface; state "not derivable from static analysis" instead of guessing; end
every generated page with a `## References` section; doc-structure page counts must be justified
per-section by a concrete signal, never symmetric "for tidiness." See
[instructions/prompt-templates.instructions.md](./instructions/prompt-templates.instructions.md).

## Conventions

- Commit style: Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`).
- `CHANGELOG.md` is Keep-a-Changelog style (`[Unreleased]` section) — update it alongside commits.
- `tests/` has **no** `__init__.py` — never `from tests.test_x import y` across test files
  (fails under pytest's default "prepend" import mode); duplicate small fixtures locally instead.
  See [instructions/testing.instructions.md](./instructions/testing.instructions.md).
