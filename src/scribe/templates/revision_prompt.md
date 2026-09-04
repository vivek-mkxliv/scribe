SCRIBE DOCUMENTATION STRUCTURE REVISION

You previously proposed a documentation structure for this repo, and it has already been
generated. The team now wants specific changes. Revise the CURRENT structure below to satisfy
their request -- keep everything that's still valid, and change only what the request calls for.
Ground any new/changed section or page in something real from the Knowledge Graph below, exactly
like the original planning rules: never default to a round number just because it looks tidy, and
never invent a source path.

## Current Structure (previously generated, with its rationale)
{current_justification}

## Current Plan (JSON)
{current_plan_json}

## Requested Changes
{revision_request}

## Project Context
{project_context}

## Graphifyy Knowledge Graph
{graphifyy_context}

## Detected CLI Surface
{cli_surface}

## Audience Mode: {audience_mode}
{audience_guidance}

Respond with ONLY a single JSON object (no prose, no markdown fences, no commentary) matching the
exact same shape as the original plan:

{{
  "mode": "{audience_mode}",
  "rationale": "1-3 sentences summarizing the overall structure after this revision",
  "sections": [
    {{
      "id": "section-slug",
      "title": "Human Title",
      "description": "what this section covers",
      "rationale": "1-2 sentences citing the concrete signal that justifies THIS section's page count, and noting what changed here (if anything) and why",
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
- Preserve the exact "id" of any page/section unaffected by the requested change -- renaming one
  loses its staleness-tracking history and forces an unnecessary regeneration even though nothing
  about its content actually changed.
- `"sources"` must be REAL file paths from the Knowledge Graph, verbatim -- never invent one.
- Output ONLY the JSON object, nothing else -- no leading/trailing text, no code fences.
