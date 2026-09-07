---
description: "Conventions for scribe's GUI/TUI surfaces (browser GUI, Textual TUI, experimental pytermgui prototype). Use when editing anything under src/scribe/gui/**."
applyTo: "src/scribe/gui/**"
---

# GUI / TUI Conventions

See [plans/08-gui-and-presets.md](../../plans/08-gui-and-presets.md) for the full design and
[testing.instructions.md](./testing.instructions.md) for test-specific gotchas (Textual
`run_test` sizing, `Static.visual`, background-thread cleanup).

1. **`gui/app.py` is the framework-agnostic core.** `resolve_form_defaults`, `build_config`,
   `RunState`, `run_generation` are shared logic — the browser server (`gui/server.py`) consumes
   them; don't duplicate this logic in `tui.py`/`tui_ptg.py`. The TUI reuses
   `resolve_form_defaults`/`build_config` but calls `pipeline.run()` directly in its own worker
   instead of going through `run_generation`/`RunState` (no HTTP boundary to poll around).
2. **The browser GUI (`gui/server.py`, `gui/static/index.html`) must stay stdlib-only** —
   `http.server`/`ThreadingHTTPServer`/`webbrowser` only, zero new pip dependencies. This is a
   deliberate design constraint, not an oversight; don't introduce a templating engine, Flask,
   etc. without an explicit ask.
3. **Bound to `127.0.0.1` only (`HOST` in `gui/server.py`).** Never change this to `0.0.0.0` or
   add a `--host` override without discussing the security implications first — the server has
   no auth and can trigger real file writes/LLM calls.
4. **Confirmation exceptions are typed as an explicit union, not bare `Exception`.**
   `_confirmation_payload` in `gui/app.py` takes the union of `TokenEstimateConfirmationRequiredError
   | OverwriteConfirmationRequiredError | CostConfirmationRequiredError` — keep new confirmation
   exception types added to `pipeline.py` reflected in that union and in
   `_CONFIRMATION_EXCEPTIONS` so mypy and the actual catch logic stay in sync.
5. **`RunState` is accessed from a background thread — always go through its lock-guarded
   methods** (`reset`/`mark_starting`/`add_message`/`finish`/`snapshot`), never read/write its
   fields directly from route handlers.
6. **`scribe tui` (`gui/tui.py`) is opt-in** via the `tui` extra (`textual>=0.60` in
   `pyproject.toml`) — the CLI command must catch `ImportError` on the lazy import and print a
   friendly `pip install scribe[tui]` message, never a raw traceback.
7. **`gui/tui_ptg.py` (pytermgui) is an experimental, unwired comparison prototype.** Do not add
   a `scribe` CLI command for it or list pytermgui as a real dependency without an explicit ask —
   pytermgui is an **archived, no-longer-maintained** project (per its own README, frozen at
   v7.8.0 as installed here). `InputField.value` is a read-only property in that library, which
   is why its preset-load only restores the mode toggle, not text fields.
