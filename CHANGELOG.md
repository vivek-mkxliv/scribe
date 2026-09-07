# Changelog

All notable changes to S.C.R.I.B.E. are documented in this file.

## [Unreleased]

Everything below was built on top of the initial core-pipeline commits (`694d09f`, `9f777c9`,
`8d78127`, `4dca210`) in one continuous session, validated against a real repo
(`jira-issue-creator`) via a locally running Ollama server (`llama3.1:8b`, then
`qwen2.5-coder:latest`).

### Added

**Per-page generation**
- Per-page LLM generation: one call per documentation page instead of one call for the whole
  suite, so a page's content depth isn't capped by splitting one output-token budget across
  every document (`generation/page_writer.py`).
- Per-page failure isolation: a page that still fails validation after all repair/retry
  attempts falls back to a placeholder stub instead of failing the entire run
  (`GenerationFailedError`, `page_writer.py`).
- Truncation-continuation, token-budget escalation, and condensed-version fallback chain for
  oversized page responses (`page_writer.py`).

**QA / prompt-grounding fixes**
- Dead-link auto-heal: when a generated page links to a real Project-Context-tree file that
  isn't part of the actual documentation suite, the fallback now strips just the broken link
  (keeping the visible text) instead of failing QA outright, as long as no other QA issue
  remains (`generation/qa.py`, `page_writer.py`).
- Mermaid QA no longer flags a style/legend-only block (`classDef` / `style` / `linkStyle` /
  `click` as the first line) as an unrecognized diagram type (`qa.py`).
- `review_documents()` now takes an explicit `known_doc_ids` (the full plan), not just the
  documents passed in the current call, and matches cross-links by basename -- required once
  generation moved to one-page-at-a-time calls (`qa.py`).
- `master_prompt.md`: explicit instruction forbidding links to Project-Context-tree files that
  aren't part of the Documentation Plan (root cause of the dead-link false positives above).
- `OpenAIClient` (covers Ollama and other OpenAI-compatible providers) now always sends an
  explicit `max_tokens` (`8192` default) instead of omitting it -- local servers otherwise apply
  their own, often much smaller, default completion length and silently truncate output
  (`providers/llm_client.py`).

**Detected CLI surface**
- `extraction/cli_surface.py`: detects a repo's real CLI commands/subcommands (argparse/click)
  so prompts can ground CLI documentation in what's actually there instead of the model
  inventing plausible-sounding flags.

**Organizational context**
- `project/org_context.py` + `scribe org-context` CLI command: scaffolds/reads
  `scribe.org.toml`, a hand-authored, optional file for facts no static analysis can produce
  (team name, contact, internal docs URL, deployment environment). Scribe never invents this --
  generated docs explicitly say when it wasn't provided.

**Dynamic, repo-derived documentation structure**
- `generation/doc_plan.py`: replaced the fixed per-mode doc list with an LLM-derived structure
  (sections of pages) grounded in real repo signals (packages, entry points, CLI subcommands),
  with a zero-cost heuristic fallback for `--dry-run` and after a failed retry.
- Per-section `rationale` (in addition to the existing plan-level one): the planner must now
  justify **each section's** page count individually, citing a concrete signal -- the actual fix
  for sections defaulting to a uniform, symmetric page count.
- `--doc-plan-file` / doc-plan conflict reconciliation (`reconcile_doc_plan`) for a user-supplied
  plan that disagrees with the recommended one.

**Plan stability, durability, and staleness**
- Doc plan cache re-keyed by stable repo identity (`extraction/cache.py::repo_identity_key`,
  path-based) instead of repo content hash, so the documentation *structure* stays stable across
  regenerations and isn't reshuffled/renamed on every content change.
- `.scribe_plan.json` is now read back as the primary source of truth
  (`pipeline._load_durable_plan`) before falling back to the user-level `~/.scribe_cache` --
  meant to be committed to version control so a teammate's fresh clone or CI reuses the exact
  same structure instead of re-deriving its own.
- Per-page content staleness detection: `DocPage.sources` (real repo file paths a page is
  grounded in, populated by the planner), `cache.compute_paths_hash`, and
  `Manifest.page_hashes` combine (`pipeline._partition_stale_pages`) so a change to one part of
  the repo no longer forces every page to regenerate -- only pages whose recorded sources
  actually changed get a new LLM call; everything else reuses its existing file untouched. Fails
  safe toward "regenerate" whenever sources are missing/unresolvable, and disabled entirely by
  `--no-incremental`.

**Structure justification, standing notes, and revision**
- `generation/justification.py` + `scribe-doc-suite-justification.md`: a dedicated,
  human-readable file explaining *why* the doc suite is shaped the way it is -- rendered fresh
  each time from the plan's rationale fields ("Current Structure": per-section page counts,
  rationale, and per-page grounding sources) plus an append-only, dated "Revision History" log.
  Written only on a true first generation or `--refresh-plan`/an explicit revision -- never
  touched by routine reuse of an unchanged durable plan.
- `project/notes.py` + `scribe.notes.md`: optional, hand-authored standing instructions/
  preferences (e.g. "always keep a single FAQ page") that persist across every future planning
  and revision call, not just a one-off input.
- `scribe revise-plan REQUEST` CLI command + `derive_doc_plan_revision_via_llm` +
  `templates/revision_prompt.md`: revise an already-generated repo's documentation structure on
  demand. Feeds the current plan, its justification history, `scribe.notes.md`, and the freeform
  request into one LLM call; the model is explicitly told to preserve page/section ids that are
  unaffected by the request (so per-page staleness tracking survives) and to preserve reasoning
  that's still valid. Updates `.scribe_plan.json` and appends to the justification log; does
  **not** regenerate page content or touch the manifest -- `scribe generate` applies the revised
  structure afterward.

### Changed
- `Manifest` gained `page_hashes: dict[str, str]` (default `{}` for backward compatibility with
  manifests written before this change).
- `DocPage` gained `sources: list[str]` (default `[]`); `DocSection` gained `rationale: str`
  (default `""`) -- both parse leniently from older plan JSON lacking the field.
- `manifest.py`/`doc_plan.py` module docstrings now state explicitly that
  `.scribe_manifest.json`, `.scribe_plan.json`, and `scribe-doc-suite-justification.md` are
  meant to be committed to version control, not gitignored.

### Fixed
- A page reused via per-page staleness skipping no longer accumulates an extra trailing newline
  on every skip cycle (`write_documents` always appends one; the reused-content read-back now
  strips it back off before the next write).

## [Unreleased] (continued — 2026-09-04/07 session)

### Added

**Anti-hallucination prompt guardrails**
- `templates/master_prompt.md`: hard top-of-file "DO NOT HALLUCINATE" rule; explicit "Unknowns"
  pattern (state plainly what isn't derivable instead of guessing); required `## References`
  section per generated page; diagrams now require a prose description + citation of real
  modules alongside the existing classDef/legend rule; concrete thinness bar (2-3 cited
  identifiers per section, banned filler phrases named explicitly); nav-tree/table guidance for
  index-style pages; cross-link rule extended to cover dangling *prose* references, not just
  dead Markdown links; explicit warning against mislabeling a page's `doc="..."` marker with a
  sibling page's id (a real failure mode observed live: a model echoed a previous page's id).
- `templates/planning_prompt.md` / `revision_prompt.md`: explicit devil's-advocate self-audit
  checklist the model must resolve before emitting JSON (is each section's page count
  independently justified, or unjustified symmetry/padding?).
- `constants.py` `AUDIENCE_MODE_GUIDANCE`: reworded "always include X/Y" to "at minimum
  include... a floor, not a target" so baseline sections aren't treated as a padding quota.
- `generation/qa.py`: new flag-grounding QA check (`_check_flag_grounding`, category
  `"ungrounded_flag"`) — flags any `--flag` token in generated content that doesn't exist
  anywhere in the real detected CLI surface (`extraction/cli_surface.py::known_flags`). Global
  existence check, not per-subcommand (regex-based subcommand scoping isn't reliable enough).
- `generation/prompt_builder.py`: the repair-loop follow-up sent back to the model for a
  single-page call now explicitly restates the exact expected doc id when repairing a
  mismatched-id failure, instead of a generic "fix the ids you got wrong" message.

**Always-on cost confirmation**
- New `TokenEstimateConfirmationRequiredError` (`pipeline.py`): before any page-generation LLM
  call, shows the *real* per-page prompt token estimate for every page about to be generated
  (not a single representative stand-in) and requires confirmation unless `--yes` — fires for
  any real run with at least one stale page, not just runs that would exceed `--token-budget`
  (that older behavior, `CostConfirmationRequiredError`, is unchanged and still checked first
  for chunking need). CLI prints a per-page token table + total before prompting.

**Per-page incremental disk writes**
- `generation/writer.py::write_document` writes a single page immediately; `page_writer.py`'s
  `generate_pages(..., output_dir=...)` calls it right after each page (or placeholder) is
  generated, so a `Generated 'x.md'.` status line always corresponds to a file already on disk
  at that moment, and a run interrupted partway through keeps everything generated so far.

**Per-repo presets**
- `project/presets.py` + `scribe.presets.json`: named, reusable configurations per repo,
  distinct from `scribe.toml` (JSON, not TOML, specifically because the GUI/TUI need to write
  this file and `tomllib` is read-only). Never stores a raw API key — only `api_key_env` (the
  env var name to read it from at run time).
- `cli.py`: new `--preset NAME` option on `generate` (precedence: explicit CLI flag > preset >
  `scribe.toml` > built-in default); `scribe presets list/show/save/delete` for CLI-only use.

**Browser GUI (`scribe gui`)**
- Local, zero-extra-dependency browser UI (`gui/server.py`, stdlib `http.server`/`webbrowser`
  only), bound to `127.0.0.1`. Form mirrors `generate`'s real flags, a preset dropdown
  (load/save/delete), a live-polling log pane, and in-page handling for all three
  confirmation-required errors instead of a terminal `click.confirm`.

**Terminal UI (`scribe tui`)**
- Textual-based TUI (`gui/tui.py`), opt-in via a new `tui` extra (`pip install scribe[tui]`) —
  `scribe gui` (the browser UI) still needs zero extra installs. Mirrors the same form/preset/
  log/confirmation flow, running `pipeline.run()` in a background Textual worker.

**Experimental: pytermgui prototype (not wired into the CLI)**
- `gui/tui_ptg.py`: a second TUI prototype built on `pytermgui`, for direct comparison against
  the Textual version before deciding which (if either, alongside the browser GUI) to keep.
  Run directly (`python -m scribe.gui.tui_ptg --repo ...`), not exposed as `scribe tui-ptg` or
  similar pending that decision. Notable finding: PyTermGUI's own docs state the project "has
  reached its final release and is no longer under active development" (archived at v7.8.0).

**Agent customization**
- `.github/copilot-instructions.md`, `.github/instructions/*.instructions.md`,
  `.github/prompts/validate.prompt.md`, `.github/agents/doc-quality-auditor.agent.md`,
  `.github/skills/scribe-live-validation/`: workspace-level Copilot customization files
  encoding this repo's build/test routine, architecture, testing gotchas, prompt-template
  guardrails, and a live-validation workflow skill.

### Changed
- `pipeline.py`'s `OverwriteConfirmationRequiredError` check now runs BEFORE per-page
  generation starts (was after generation, before the final batch write) — moved up because
  per-page writes now land on disk incrementally, so it would otherwise be too late to ask.
- `project/presets.py::save_preset` now refuses to save only when `api_key` is a **truthy**
  secret (`values.get("api_key")`), not merely present as a key — the browser GUI/TUI form
  submissions always include an `api_key` field (blank if unset), so the original "key present"
  check rejected *every* preset save from either UI.

### Fixed
- `save_preset` blank-`api_key` false-positive rejection described above (affected every preset
  save from the browser GUI and TUI since the browser GUI first shipped, never caught because
  the initial HTTP-level tests posted hand-built bodies that happened to omit `api_key`).

