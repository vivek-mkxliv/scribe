---
description: "Testing conventions for scribe's pytest suite: fixture patterns, FakeLLMClient usage, known gotchas around cross-test imports, doc-id scoping, and manifest/staleness assertions."
applyTo: "tests/**"
---

# Testing Conventions

- **No `tests/__init__.py`.** Never `from tests.test_x import y` across test files — fails under
  pytest's default "prepend" import mode. Duplicate small fixtures locally instead of importing.
- **Canonical fixtures** live in `tests/test_pipeline_incremental.py`: `FakeLLMClient` /
  `_config(tmp_path, **overrides)` / `_write(path, content)`. `FakeLLMClient` detects
  `PLANNER_MARKER`/`REVISION_MARKER` (from `generation/doc_plan.py`) in the prompt to know
  whether to return a plan JSON or page content — reuse this pattern for any new pipeline test.
- **Doc-id scoping in fake per-page clients.** Every per-page prompt contains ALL page ids (the
  target page under "Your Assignment", but every sibling is listed again in the "Full
  Documentation Plan" cross-link section). A naive `doc_id in prompt` substring check matches the
  wrong page — scope the match to text after `"Your Assignment"` instead. **Corollary for
  `master_prompt.md` edits**: this scoping trick uses `prompt.rfind("Your Assignment")` (last
  occurrence) — if you add wording elsewhere in the template that repeats the literal phrase
  "Your Assignment" AFTER the real `## Your Assignment` heading (e.g. in a closing instruction
  paragraph), `rfind` finds that later occurrence instead and the scoped `tail` slice silently
  loses the real assignment content, breaking every per-page test. Verified by hitting this
  exact break while adding a repair-loop guardrail sentence — reworded to avoid repeating the
  phrase instead of relying on this being caught by chance.
- **Trailing newline on written pages.** `write_documents` always appends a trailing `"\n"`.
  Code that reads a page back to reuse its raw content verbatim (e.g. a staleness skip-reuse
  path) must `.removesuffix("\n")` first or it accumulates an extra newline every cycle.
- **Second-`run()` tests must actually change something.** A test asserting behavior on a SECOND
  `run()` call must change repo content (or a flag) between the two calls, or the top-level
  whole-repo `manifest.is_up_to_date()` skip fires first and the run makes zero LLM calls
  regardless of what else you changed (e.g. a different `cache_dir`).
- **`FakeLLMClient.call_count` assertions are exact.** Adding a new LLM roundtrip anywhere in the
  planning/generation path (e.g. a self-audit pass) will break these — think about call-count
  impact before adding any new LLM call to a shared code path.
- **`assume_yes=True` is required for any real generation call.** `pipeline.run()` raises
  `TokenEstimateConfirmationRequiredError` before any page-generation LLM call whenever there's
  at least one stale page and `assume_yes` isn't set (an always-on cost-confirmation gate, not
  just the pre-existing over-budget `CostConfirmationRequiredError`). Tests exercising a real
  `run()` must pass `assume_yes=True` unless they're specifically testing this confirmation gate
  or `OverwriteConfirmationRequiredError` (which is still checked first).
- **Background threads in GUI tests must finish before the test function returns.**
  `gui/app.py` does `from scribe import pipeline` (the module object, not just the function), so
  `monkeypatch.setattr("scribe.gui.app.pipeline.run", fake)` patches the real, shared
  `scribe.pipeline` module globally -- not a private copy scoped to one test. A background
  generation thread (`gui/server.py` spawns one per `POST /api/generate`) left running past its
  own test's scope resolves `pipeline.run` dynamically at call time and can pick up whatever
  ANOTHER test has since monkeypatched it to, corrupting that other test's call count/results.
  Always wait for completion (poll `GET /api/status` until `not running`, or `thread.join()`)
  before a GUI test returns -- confirmed by hitting this exact flake in practice.
- **Textual TUI tests (`test_gui_tui.py`) need `App.run_test(size=(120, 60))`.** The default
  test terminal size (80x24) is too small for the form layout -- `pilot.click(...)` on a widget
  outside the (too-small) default viewport raises `OutOfBounds`. No `pytest-asyncio` dependency
  is added for these; wrap the async `run_test()` scenario in a plain `asyncio.run(...)` instead.
- **Read a Textual `Static` widget's current text via `str(widget.visual)`, not
  `.renderable`.** The installed `textual` version (8.2.8) has no `.renderable` attribute on
  `Static` -- confirmed via runtime introspection, not docs (version-specific gotcha, re-check if
  `textual` is upgraded).
- **pytermgui's `InputField.value` is a read-only property** (verified via
  `inspect.getsource`/mypy: "Property 'value' defined in 'InputField' is read-only"). This is why
  `gui/tui_ptg.py` (the experimental, unwired pytermgui prototype) only restores the mode toggle
  on preset-load, not text fields -- don't attempt to assign `.value` directly if extending that
  file.
