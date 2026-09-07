SCRIBE DOCUMENTATION STRUCTURE PLANNER

You are planning the documentation STRUCTURE for a codebase -- not writing content yet.

DO NOT HALLUCINATE: every section/page must be grounded in something real below (a detected
language, entry point, package, workflow, or CLI subcommand); a `"sources"` path that doesn't
appear verbatim in the Knowledge Graph is worse than an empty list, because it will be trusted
for staleness tracking. Never assume or cross-reference details from other repos/prior knowledge
that aren't shown below.

Analyze the project context and knowledge graph below and propose a documentation structure:
a set of top-level sections, each containing one or more pages. Ground every section and page in
something real you can see below (a detected language, an entry point, a package, a workflow) --
never default to a round number like "3" or "5" pages just because it looks tidy. A tiny
single-module script may only need one or two pages total; a 40-package monorepo may need a dozen
sections. Derive the count from what's actually here.

Do NOT give every section the same page count purely for visual symmetry (e.g. "2 pages per
section" across the board is a red flag, not a goal). A section covering one simple workflow
might need exactly 1 page; a section covering several distinct subsystems or a real detected CLI
with multiple subcommands should have one page per subcommand/subsystem, not a fixed count. Both
the top-level "rationale" AND each section's own "rationale" must justify that section's page
count in terms of something concrete below (a specific number of packages, entry points, or
detected CLI subcommands) -- if you can't point to a concrete reason for a section's page count,
that's a sign it's arbitrary and should change.

SELF-AUDIT (do this before you output anything) -- play devil's advocate against your own draft
structure, out loud to yourself, before finalizing:
- Look at the page count of every section side by side. If two or more sections have the same
  count, can you point to an independent, concrete reason each one landed there (not "it felt
  balanced")? If not, revise one of them now.
- For each section, ask: "would a new user actually need a separate page for this, or did I
  split/pad it to make the suite look more complete?" Merge pages that don't earn their own
  space; split a page that's really covering 3 unrelated subsystems.
- Different audiences need different shapes, not a shared template -- a CLI-only tool aimed at
  its own maintainers may need almost no "user guide" content and a lot of architecture depth; a
  tool with many non-technical operators may need the opposite. Let the audience mode guidance
  below and the repo's actual signals (not a habit of "always have N sections") decide the split.
- If, after this audit, you still land on a symmetric-looking structure, that's fine -- but only
  if the rationale you write actually names the concrete signal for EACH section independently,
  not a single sentence covering all of them at once.

## Project Context
{project_context}

## Graphifyy Knowledge Graph
{graphifyy_context}

## Detected CLI Surface
{cli_surface}

## Audience Mode: {audience_mode}
{audience_guidance}

## Standing Notes From The Team
{user_notes}

Respond with ONLY a single JSON object (no prose, no markdown fences, no commentary) matching this
exact shape:

{{
  "mode": "{audience_mode}",
  "rationale": "1-3 sentences citing concrete counts/signals (packages, entry points, CLI subcommands) that justify this specific section/page structure",
  "sections": [
    {{
      "id": "section-slug",
      "title": "Human Title",
      "description": "what this section covers",
      "rationale": "1-2 sentences citing the concrete signal that justifies THIS section's specific page count",
      "pages": [
        {{
          "id": "section-slug/01-page-name.md",
          "title": "Page Title",
          "description": "what this page covers",
          "sources": ["real/file/path/from/the/knowledge/graph.py"]
        }}
      ]
    }}
  ]
}}

Rules:
- Every page "id" must start with its parent section's "id" followed by "/" and end in ".md".
- Page ids must be unique, lowercase, kebab-case.
- `"sources"` is a list of the REAL file paths (verbatim, exactly as shown in the Knowledge
  Graph's Modules list above) that this specific page is most grounded in -- used later to
  detect when a page's underlying source changed and it needs regenerating. Leave it an empty
  list if no specific files apply (e.g. a purely conceptual/overview page); never invent a path.
- Honor the Standing Notes above whenever they conflict with a default heuristic in these
  instructions, but never let them override a concrete repo signal with a fabricated fact.
- Output ONLY the JSON object, nothing else -- no leading/trailing text, no code fences.


