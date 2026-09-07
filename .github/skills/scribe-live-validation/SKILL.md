---
name: scribe-live-validation
description: 'Live-validate scribe by generating a real documentation suite against a target repo with a local/remote LLM, then auditing the output for hallucination, thinness, dangling references, and structural issues. Use when the user asks to "test scribe against a real repo", "live-validate", "re-run generation and check quality", or after changing prompt templates/QA checks and wanting to confirm the change actually helped.'
argument-hint: 'Target repo path, mode (lean_technical/operator_split), provider/model, max-tokens'
---

# Scribe Live Validation

## When to Use
- After changing `src/scribe/templates/*.md` or `generation/qa.py`, to confirm a guardrail change
  actually reduces the specific failure mode it targeted (not just that unit tests still pass).
- When the user wants a real end-to-end run against an external repo, not scribe's own repo.

## Procedure

1. **Confirm inputs** with the user if not given: target repo path, `--mode`
   (`lean_technical`/`operator_split`), `--provider`/`--model` (default to a locally running
   Ollama model if reachable — check `http://localhost:11434/api/tags` first), `--max-tokens`,
   and an `--output` folder name that won't collide with a previous run's output (e.g.
   `docs-operator-split` alongside the default `docs`).

2. **Run generation** using the venv interpreter, in a **background terminal dedicated to this
   run only**:
   ```powershell
   & "<scribe-repo>/.venv/Scripts/python.exe" -m scribe.cli generate --repo "<target-repo>" `
     --mode <mode> --output <output-dir> --provider <provider> --model <model> `
     --max-tokens <n> --yes
   ```
   **Never** send another command into that same terminal while it's running — a diagnostic
   command interleaved with a long-running foreground `scribe generate` has aborted a run before
   (checking process status via a new command in the busy terminal killed the generation). Use a
   separate terminal for anything else, or just wait for completion.

3. **Once generation completes**, check for the cheap/mechanical signals first:
   - List all output files with sizes.
   - Search all `.md` files for `placeholder|could not be generated` (case-insensitive) — any
     hit means a page fell back after exhausting repair attempts.

4. **Then invoke the `doc-quality-auditor` subagent** (or perform its procedure directly) against
   the output directory to check for hallucinated flags, contradictions, thinness, dangling
   references, missing `## References` sections, and unjustified symmetric structure.

5. **Report back**: a pass/fail summary of the mechanical checks, then the auditor's findings
   grouped by category, then (if this run followed a guardrail change) an explicit statement of
   whether the specific issue that motivated the change actually stopped occurring.

## Notes
- Each live run costs real wall-clock time (a multi-page suite makes one LLM call per page plus
  repair/fallback attempts) — don't re-run speculatively; confirm scope with the user first if
  it's not already clear from the conversation.
- See [conventions](../copilot-instructions.md) for the fail-safe design principle this tool is
  built around — a finding here should usually map to "which fail-safe default did this violate"
  when proposing a fix.
