---
description: "Run scribe's full validation routine (ruff format, ruff check, mypy, pytest) and summarize any failures."
agent: "agent"
---
Run the project's standard validation routine, in this exact order, using the venv interpreter
(never bare `python`/`py`):

1. `& "${workspaceFolder}/.venv/Scripts/python.exe" -m ruff format .`
2. `& "${workspaceFolder}/.venv/Scripts/python.exe" -m ruff check .`
3. `& "${workspaceFolder}/.venv/Scripts/python.exe" -m mypy src/scribe --ignore-missing-imports`
4. `& "${workspaceFolder}/.venv/Scripts/python.exe" -m pytest -q`

If any step fails:
- For `ruff format`/`ruff check`: fix violations directly (note that `ruff format` does not
  auto-split long lines — an E501 left behind needs a manual fix, e.g. splitting an f-string
  into a parenthesized concatenation).
- For `mypy`: fix the type error at its source rather than adding a blanket `# type: ignore`.
- For `pytest`: read the failing test's assertion and traceback before changing anything; check
  [testing conventions](../instructions/testing.instructions.md) for known gotchas (cross-test
  imports, doc-id scoping in fake LLM clients, `call_count` assertions) before assuming it's a
  new bug.

Re-run all four after any fix until all pass. Report a concise final summary: pass/fail per step,
test count, and anything fixed along the way.
