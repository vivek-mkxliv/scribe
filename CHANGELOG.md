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
