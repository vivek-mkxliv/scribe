# Plan 08 — GUI, TUI, and Per-Repo Presets

**Goal:** let a non-power-user run S.C.R.I.B.E. without memorizing CLI flags, via an explicit
`scribe gui` command, while power users keep using `scribe generate` exactly as today. Presets
(named, reusable configurations) are shared infrastructure both the GUI and CLI can use.

## Decisions (locked in 2026-09-04, after reviewing options with the user)

- **Two UI surfaces, not one**: a local browser-based UI (default) and a Textual TUI (opt-in),
  both launched only via an explicit `scribe gui` command -- never on bare `scribe` invocation,
  so scripted/CI usage of the CLI is never accidentally affected.
  - Browser UI: **zero new dependencies** -- stdlib `http.server`/`socketserver` + `webbrowser`,
    bound to `127.0.0.1` only. Chosen over Tkinter because it can look modern (real HTML/CSS)
    with less hand-rolled widget code, and over Textual-as-default because it adds no dependency
    at all for the common case.
  - TUI: `scribe gui --tui`, built on `textual` (pure-Python, MIT, same maintainers as `rich`
    which is already a dependency) -- installed via a new optional extra (`pip install
    scribe[tui]`), not a hard dependency, so the zero-dependency default path is unaffected.
- **Presets**: a new `scribe.presets.json` file per repo (NOT an extension of `scribe.toml`).
  Rationale: `tomllib` (stdlib) is read-only -- there's no stdlib TOML writer -- and the GUI
  needs to be able to save/overwrite presets. JSON is trivially read/write via stdlib `json`,
  and this matches the existing "one small file per concern" convention (`scribe.org.toml`,
  `scribe.notes.md`). `scribe.toml`/`[tool.scribe]` stays exactly what it is today (hand-authored
  blanket defaults); a preset is a named, more specific override on top of it.
- **Precedence** (highest wins, extending the existing rule in `config_loader.py`): explicit CLI
  flag > `--preset NAME` values > `scribe.toml`/`[tool.scribe]` values > built-in default.

## Phases

### Phase 1 — Presets (foundation for both UIs)
- [x] `project/presets.py`: `Preset` dataclass (subset of `CONFIG_FIELDS` + provider/model/
  api-key-env-var-name/max-tokens/temperature -- never the raw API key itself, see Security
  below), `load_presets(repo_path) -> dict[str, Preset]`, `save_preset(repo_path, name, preset)`,
  `delete_preset(repo_path, name)`. Missing file -> `{}`, never an error (fail-safe default).
- [x] `cli.py`: new `--preset NAME` option on `generate`, applied at the precedence tier above.
  `scribe presets list/show/save/delete` companion commands for CLI-only parity.
- [x] Tests: round-trip save/load, missing-file default, unknown-field tolerance (mirrors
  `config_loader.py`'s "ignore unknown keys" fail-safe pattern), precedence ordering.
  `tests/test_presets.py` (13 tests) + 5 new CLI-level tests in `tests/test_cli.py`.

**Security note**: never persist a raw API key in `scribe.presets.json` (it's meant to be
committed alongside `scribe.toml`/`.scribe_plan.json` per existing convention -- a committed API
key would be a real credential leak). Store only the env var *name* the key should come from
(e.g. `"api_key_env": "ANTHROPIC_API_KEY"`), matching how `--api-key` already falls back to
`SCRIBE_API_KEY` today.

### Phase 2 — Browser GUI (`scribe gui`, default)
- [x] `gui/server.py`: minimal stdlib `http.server` app -- serves one static page, a `POST
  /api/generate` endpoint that runs `pipeline.run()` on a background thread, a `GET
  /api/status` polling endpoint streaming `on_status` messages, `GET`/`POST`/`DELETE
  /api/presets(/<name>)` for load/save/delete. Bound to `127.0.0.1` only, OS-assigned ephemeral
  port by default (`--port` to override), opens the user's default browser via
  `webbrowser.open()`, shuts down cleanly on Ctrl+C.
- [x] `gui/static/index.html` (+ inline CSS/JS, no build step, no framework): a form mirroring
  `generate`'s real flags, a preset dropdown (load populates the form; a "Save as preset"
  button writes one back), a live log pane (polls `/api/status`), and inline handling for the
  three confirmation errors as an in-page "Proceed?" prompt instead of a terminal
  `click.confirm`.
- [x] Tests: `tests/test_gui_app.py` (framework-agnostic logic: form defaults/precedence,
  `build_config`, `RunState`, `run_generation` including confirmation/error/concurrency paths)
  + `tests/test_gui_server.py` (real HTTP requests against a real server on `127.0.0.1:0`, no
  mocking of `http.server` internals; `pipeline.run` monkeypatched so no real LLM call happens).
  22 new tests. Found and fixed a real cross-test contamination hazard along the way: a daemon
  thread from one test outliving that test's `monkeypatch` scope resolves `pipeline.run`
  dynamically at call time against the real, shared `scribe.pipeline` module object (since
  `gui/app.py` does `from scribe import pipeline`) -- every test that starts a background
  generation must wait for it to finish before returning. Also hardened tests to mock provider
  resolution rather than depending on a real local Ollama server being reachable.

### Phase 3 — TUI (`scribe tui`, opt-in extra)
- [x] Added `textual` under a new `[project.optional-dependencies] tui = ["textual>=0.60"]` extra
  (installed in the dev venv for development/testing; not a hard dependency).
- [x] `cli.py`: new top-level `scribe tui` command (changed from the originally-considered
  `scribe gui --tui` on 2026-09-04 -- a distinct top-level command is clearer than a flag on
  `gui` and matches `scribe gui` being its own command rather than a mode switch). Catches
  `ImportError` and prints a friendly `pip install scribe[tui]` message instead of a bare
  traceback when the extra isn't installed.
- [x] `gui/tui.py`: a Textual `App` (`ScribeTuiApp`) mirroring the same form/preset/live-log/
  confirmation flow as the browser UI -- reuses `gui/app.py`'s `resolve_form_defaults`/
  `build_config` and `project/presets.py` directly, but calls `pipeline.run()` in a Textual
  `@work(thread=True)` background worker (not the HTTP-polling `RunState`/`run_generation`,
  which exists specifically to work around the browser's request/response boundary -- not
  needed here since the TUI is in the same process).
- [x] Tests: `tests/test_gui_tui.py` (6 smoke tests) using Textual's own `App.run_test()` async
  harness, run via plain `asyncio.run()` (no `pytest-asyncio` dev dependency added). Covers:
  defaults on mount, `scribe.toml` layering, save/delete preset via button click, generate
  reaching `pipeline.run()` and reporting done, and the confirmation-required flow appearing.

**Real bug found and fixed while building this (affects the browser GUI too, not just the
TUI)**: `project/presets.py::save_preset` rejected ANY save that included an `api_key` key at
all, even a blank one -- but both the browser GUI's `currentForm()` and the TUI's
`_current_form()` always include `api_key` (empty string if the field is blank) when saving a
preset. This meant **every single preset save from either UI was broken**, always raising
`PresetError`, since day one of Phase 2 -- never caught because the Phase 2 HTTP tests posted to
`/api/presets/<name>` directly with hand-built bodies that happened to omit `api_key`, not via
the real form-gathering JS. Fixed by checking `values.get("api_key")` (truthy secret) instead of
`"api_key" in values` (mere presence). Added a regression test
(`test_saving_a_blank_api_key_is_not_refused`) in `tests/test_presets.py`.

## Explicit non-goals (avoid over-engineering)
- No bare `scribe` (no subcommand) auto-launching the GUI -- always explicit `scribe gui`.
- No new GUI-only config fields beyond what `generate` already exposes as CLI flags.
- No attempt to make the browser UI multi-user/networked -- single local user, `127.0.0.1` only.
