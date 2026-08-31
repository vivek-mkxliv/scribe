# Installation Doc Placeholder

Scratch notes to fold into the real installation documentation once it's generated/written
(User Manual for `lean_technical`, or User Guides + Technical User Docs for `operator_split`).
Not meant to ship as-is -- it's a source-of-truth capture of decisions made during development
so they aren't lost before the real docs exist.

## Install Paths

| Command | Gets you | Trade-off |
|---|---|---|
| `pip install scribe[graphifyy]` (recommended) | Real Graphifyy AST/knowledge-graph extraction, zero extra manual steps | Pulls in ~25 tree-sitter language grammars + `networkx`/`numpy`; larger, slower install |
| `pip install scribe` (plain) | Built-in native AST/regex fallback extractor | Coarser knowledge graph (file-level, not function/class-level); no extra install weight or native-extension compatibility risk |

Both paths produce a working `scribe generate`. The difference is extraction fidelity, not
whether the tool works at all.

## Why `graphifyy` Is an Optional Extra, Not a Hard Dependency

Declared under `[project.optional-dependencies]` in `pyproject.toml`, not the core
`dependencies` list. Reasoning:

- `graphifyy` pulls in real weight: ~25 separate `tree-sitter-<language>` packages (native
  compiled extensions, one per supported language) plus `networkx`, `numpy`, `rapidfuzz`.
- That's a real risk on locked-down/air-gapped corporate machines -- exactly the environment
  some engineers on an ADAS/simulation team work in (C++/C#/Unreal-first, not necessarily
  Python-first) -- where a large native-extension install can fail outright (no internet, a
  restricted package mirror, missing build tools for a wheel that isn't prebuilt for the
  platform).
- The native fallback extractor already exists and is fully supported specifically to cover
  that case, so making `graphifyy` optional turns a potential hard failure into a graceful,
  documented degradation instead.

**To reverse this decision later:** move `"graphifyy>=0.9"` out of
`[project.optional-dependencies]` and into the top-level `dependencies = [...]` list in
`pyproject.toml`. That's the entire change -- `pip install scribe` would then always include
real Graphifyy, and the native fallback becomes a runtime safety net rather than an
intentional lightweight-install option.

## How the Executable Is Found (worth a line in Troubleshooting docs)

`graphify`'s executable is looked up next to the running Python interpreter first
(`extractor._find_graphify_executable()`), before falling back to a plain `PATH` lookup. This
matters because installing `graphifyy` into the same virtual environment as scribe does **not**
put it on `PATH` unless that environment is "activated" in the current shell -- and scribe is
often invoked via a direct interpreter path (e.g. a VS Code task or script calling
`.venv/Scripts/python.exe` directly) where activation never happens.

## Open Item for Real Docs

- [ ] Decide final wording/placement once the actual generated User Manual / Technical Docs exist -- this file is a holding pen, not the final copy.
- [ ] Confirm whether the parent-company's standard engineering environment already has `graphifyy`'s tree-sitter wheels cached/mirrored internally, which would change the "recommended default" recommendation above.
