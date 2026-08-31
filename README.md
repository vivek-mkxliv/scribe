# S.C.R.I.B.E.
# pyDocuJinn
**System Context & Repository Intelligence Bridge Engine**

A standalone CLI that generates multi-tiered, audience-aware documentation suites for any codebase, using an AST/knowledge-graph pass (Graphifyy, with a built-in native fallback when Graphifyy isn't installed) instead of flattening the repo into an LLM context window.

## Pipeline
1. **Context Extraction** — Graphifyy (or, if unavailable, a built-in native AST/regex extractor) parses the repo into a `GraphContext`, cached by content hash.
2. **Prompt Assembly** — the graph digest + repo structure + `--mode` are injected into the master template, auto-shrinking the digest to fit `--token-budget`.
3. **LLM Orchestration** — the assembled prompt is sent to any of several providers (see `scribe models` / [MODELS.md](MODELS.md)), with automatic retry/backoff and a repair loop that re-prompts on malformed or QA-failing output.
4. **File System Writing** — each document is matched by an explicit `<!-- SCRIBE:BEGIN doc="..." -->` marker (not a positional `---` split) and written to `/docs`.

## Modes
- `lean_technical` — 4-part suite for internal R&D teams (README, User Manual, Troubleshooting, Dev Playbook).
- `operator_split` — 8-part suite with strict operator/engineer separation (Home, Docs Home, User Guides, Troubleshooting, FAQs, Contact Us, Technical User Docs, Dev Docs).

## Quick Start
```bash
pip install -e ".[graphifyy]"     # recommended: also installs the real Graphifyy extractor
scribe init                       # optional: writes scribe.toml with your project defaults
scribe models                     # see supported providers and recommended models
scribe generate --mode lean_technical --repo . --output ./docs --api-key sk-ant-...
```

`pip install -e .` (without `[graphifyy]`) works too and falls back to a built-in native
AST/regex extractor -- a real option for locked-down/air-gapped machines, just with a coarser
knowledge graph. Pass `--api-key` and the provider is auto-detected from its format (or from an
env var like `ANTHROPIC_API_KEY`/`GROQ_API_KEY`); with no key at all, S.C.R.I.B.E. uses a locally
running Ollama server if found, or prints free/paid setup options otherwise. Use `--dry-run` to
inspect the assembled prompt without calling the LLM, and `--check` for a CI-safe, no-LLM-call
drift check. See [MODELS.md](MODELS.md) for free/local (Ollama, Groq, OpenRouter) vs. paid
provider options, and how to add a new provider.

### Why `graphifyy` is optional, not a hard dependency

`graphifyy` pulls in ~25 tree-sitter language grammars plus `networkx`/`numpy` -- real install
size/time/compatibility cost, and a risk on locked-down/air-gapped machines. It's declared under
`[project.optional-dependencies]` in `pyproject.toml` rather than in the core `dependencies` list
specifically so a plain `pip install scribe` still works everywhere via the native fallback
extractor. See [installation-doc-placeholder.md](installation-doc-placeholder.md) for the full
writeup to fold into the real installation docs later.
