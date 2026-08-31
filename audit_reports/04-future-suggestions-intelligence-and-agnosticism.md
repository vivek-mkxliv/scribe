# 04 — Future Suggestions: Smarter, More Intelligent, More Project-Agnostic

Concrete, specific ideas — not "add more AI." Each one names the exact file/mechanism it builds
on and why it's worth doing.

**Structural note:** this was originally written as two flat lists of five items each. On
re-reading my own wording, that 5-and-5 shape was a stylistic default, not a genuine reflection of
how much each idea is worth — some items were already explicitly called "highest-leverage" and
others "lower priority" in their own paragraphs, and two were tightly coupled enough that they
should never have been separate headings. Re-cut below by actual merit: three core ideas worth
doing first, three adjacent/combinable ones worth doing together once the core three land, and one
genuinely long-term item. Each item still notes whether it's a "smarter" or "project-agnostic"
contribution (or both) — that framing was useful, it just shouldn't have been the top-level
structure.

## Tier 1 — Core (do these first, highest leverage)

### 1. Stop discarding the confidence signal you already have *(smarter)*
Graphifyy tags every edge `EXTRACTED` (explicit in source) / `INFERRED` (a deduction, with a
0.55–0.95 confidence score) / `AMBIGUOUS` (flagged for human review). `parse_graphifyy_output`
currently reads only `source`/`target` off each link and throws the rest away when aggregating
to file-level edges. Concrete change: carry `confidence`/`confidence_score` through to
`DependencyEdge`, and instruct the master prompt to hedge language around `INFERRED`/`AMBIGUOUS`
relationships ("likely depends on," not "depends on") and to flag `AMBIGUOUS` ones explicitly in
the Dev Playbook/Dev Docs. This remains the single highest-leverage change available — the data
already exists, it's just being dropped on the floor.

### 2. A real "does this doc match the code" verification pass *(smarter)*
The QA pass (`generation/qa.py`) checks Mermaid syntax, dead links, and placeholder text — all
*structural* checks. None of them verify the doc is *factually accurate* about the codebase.
Add an optional (flagged, since it costs another LLM call) verification pass: feed the generated
Dev Playbook back to the model alongside the graph digest with the prompt "list any claim in this
document that is not supported by the provided graph." This is the natural next step beyond
structural QA, and it directly hedges the single biggest unverified risk named in report 01 and
`unbiased_judjement.md`.

### 3. Smarter chunking: package-level caching + repo-shape-aware grouping *(smarter + agnostic)*
Two ideas that turned out to be the same mechanism on reflection, merged: `.scribe_manifest.json`
currently tracks one hash for the *entire* repo, and chunking (`generation/chunking.py`) currently groups
by top-level directory unconditionally, regardless of whether that produces sensible package
sizes. Both are really "how do we partition a repo for map-reduce" — solve them together: detect
repo shape first (max depth, file distribution) to choose grouping granularity, then cache each
resulting package's summary independently (keyed by a hash of just that package's files). A change
to one module in a 40-package monorepo then re-summarizes one package and reuses the rest — a real
cost/latency win that compounds with repo size, exactly where chunking already kicks in.

## Tier 2 — Adjacent / Combinable (real value, decide and build together)

### 4. Configurable doc-suite + overridable templates (+ stack-aware tone) *(agnostic)*
Three previously-separate items, combined because they're the same underlying gap: `DOC_SUITE` in
`constants.py` hardcodes exactly two structures (4-doc, 8-doc); there's no way to override
`templates/master_prompt.md`; and prompt tone is generic regardless of the detected stack (a repo
that's 80% C++ with Unreal markers gets the same framing as a web service). All three are solved
by the same mechanism: a `[tool.scribe.docs]` table in `scribe.toml` for custom doc ids/
descriptions/tone, a `--template-dir` override checked before the packaged default, and a
detected-stack hint (`GraphStats.languages` already computes this) appended to `project_context`
as one more piece of that same template data. This is the most direct fix for the "rigid
structure" disadvantage in report 02, and turns scribe from "produces these two specific doc sets"
into "a documentation-generation engine with a sensible default."

### 5. Learn the team's voice from hand-edits *(smarter)*
The overwrite-confirmation logic already detects when `output_dir` contains files scribe doesn't
own. Extend this: when a *scribe-owned* doc is hand-edited between runs (detectable — the file's
content hash no longer matches what scribe last wrote, per doc, not just per repo), diff the edit
and feed a short "the team preferred this phrasing/structure" note into the next regeneration's
prompt. Grouped in this tier, not tier 1, because it's the most mechanically speculative idea here
— it needs per-doc hash tracking and a diff-to-instruction step that doesn't exist yet, versus the
tier-1 items which extend data/passes already flowing through the pipeline.

### 6. Close the native-fallback quality gap for the team's own stack *(agnostic)*
Report 02's disadvantage #4: non-Python native-fallback extraction is regex-based. Replace the
regex import-scanners with the `tree-sitter` Python bindings directly (a much lighter dependency
than the full `graphifyy` package — a handful of grammar packages for the languages this team
actually uses, not all ~25) as a *second-tier* fallback: Graphifyy (best) → lightweight
tree-sitter (better than regex) → regex (last resort). Grouped here rather than tier 1 because it's
a real, separate infrastructure investment (a new dependency, a new extraction tier) rather than
an extension of existing data flow — but it directly serves the team's stated C++/C#/Unreal-heavy
reality, so it shouldn't be mistaken for optional polish either.

## Tier 3 — Long-Term, Lower Priority

### 7. Provider/mode extensibility via entry points, not hardcoded dicts *(agnostic)*
`PROVIDER_PRESETS` and `DOC_SUITE` are both plain dicts in source — easy to *edit*, not extensible
without editing scribe's own source. The correct long-term direction, if this tool is ever meant to
outgrow this one team: expose both via Python entry points (`scribe.providers`, `scribe.doc_modes`)
so a third party can add a provider or a doc mode by installing a small separate package, with zero
changes to `scribe` itself. This is the one item in this document that is genuinely speculative and
distant rather than merely lower-effort — it only pays off if scribe gets external adopters, which
is a later-stage problem than anything in tiers 1–2.

