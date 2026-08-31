SCRIBE DOCUMENTATION STRUCTURE PLANNER

You are planning the documentation STRUCTURE for a codebase -- not writing content yet.

Analyze the project context and knowledge graph below and propose a documentation structure:
a set of top-level sections, each containing one or more pages. Ground every section and page in
something real you can see below (a detected language, an entry point, a package, a workflow) --
never default to a round number like "3" or "5" pages just because it looks tidy. A tiny
single-module script may only need one or two pages total; a 40-package monorepo may need a dozen
sections. Derive the count from what's actually here.

## Project Context
{project_context}

## Graphifyy Knowledge Graph
{graphifyy_context}

## Audience Mode: {audience_mode}
{audience_guidance}

Respond with ONLY a single JSON object (no prose, no markdown fences, no commentary) matching this
exact shape:

{{
  "mode": "{audience_mode}",
  "rationale": "1-3 sentences on why this structure fits this specific repo",
  "sections": [
    {{
      "id": "section-slug",
      "title": "Human Title",
      "description": "what this section covers",
      "pages": [
        {{"id": "section-slug/01-page-name.md", "title": "Page Title", "description": "what this page covers"}}
      ]
    }}
  ]
}}

Rules:
- Every page "id" must start with its parent section's "id" followed by "/" and end in ".md".
- Page ids must be unique, lowercase, kebab-case.
- Output ONLY the JSON object, nothing else -- no leading/trailing text, no code fences.
