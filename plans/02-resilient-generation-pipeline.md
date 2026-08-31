# Plan 02 — Resilient, Structured Generation Pipeline

**Goal:** replace the single-shot, positional `---`-split LLM call with a structured, retry-capable, self-checking pipeline that scales past one context window and never writes garbage to disk.

## Current State

[`src/scribe/pipeline.py`](../src/scribe/pipeline.py) makes exactly one LLM call and hands the raw response to [`src/scribe/generation/writer.py`](../src/scribe/generation/writer.py) *(moved from `core/writer.py`)*, which:

- Splits on the literal string `"\n---\n"` — a Markdown horizontal rule, a stray Mermaid `---` in frontmatter, or the model paraphrasing the divider all silently corrupt the split.
- Maps sections to filenames **by position**, so if the model skips, merges, or reorders a doc, the wrong content lands in the wrong file with no warning.
- Raises `DocumentCountMismatchError` and gives up entirely — no repair attempt, no partial write, the user gets nothing and burned tokens.

There is also no retry/backoff on transient API failures, no streaming feedback (a multi-minute call looks hung), no token/cost estimate before spending money, and the default model string in `cli.py` is a guess, not a confirmed slug.

## Goals

1. Make the LLM output contract robust to reordering, omission, and incidental `---` usage.
2. Add an automatic repair loop instead of a hard failure when output doesn't match the contract.
3. Support map-reduce style chunked generation for repos whose graph digest still doesn't fit one call.
4. Add retries/backoff for transient provider errors, streaming feedback, and pre-flight cost/token estimation.
5. Add a post-generation QA pass that catches bad Mermaid syntax, dead internal links, and leftover placeholder text before anything is written.

## Tasks

- [x] **2.1** Replace the `---`-divider contract with explicit named markers, e.g. `<!-- SCRIBE:BEGIN doc="README.md" -->` / `<!-- SCRIBE:END -->`, in [`templates/master_prompt.md`](../src/scribe/templates/master_prompt.md). Update `writer.split_sections` to parse by marker + doc id, not position, and to detect duplicates/missing ids by name instead of count. *(Implemented as `writer.parse_sections`/`validate_sections`.)*
- [x] **2.2** Add `writer.validate_sections(sections, expected_ids) -> ValidationResult` that reports exactly which doc ids are missing/duplicated/extra (not just a count mismatch).
- [x] **2.3** Add a **repair loop** in `pipeline.py`: on `ValidationResult` failure, re-prompt the same LLM call with a short follow-up message naming the specific missing/malformed doc ids, up to `--max-repair-attempts` (default 2), before failing. *(`pipeline._generate_with_repair`.)*
- [x] **2.4** Add token estimation (`tiktoken` for OpenAI-family models, provider-native counting or a conservative heuristic for others) in `generation/tokens.py` *(moved from `core/tokens.py`)*. *(Estimation + auto-shrinking digest via `pipeline._build_bounded_prompt`. Pre-flight cost confirmation implemented as `CostConfirmationRequiredError`, gated by `--yes`/`-y`, reusing `--token-budget` as the threshold per team decision — the CLI catches it, shows the estimate, and interactively confirms via `click.confirm` before retrying once.)*
- [x] **2.5** Implement chunked/map-reduce generation: when the digest from Plan 01 is still too large, run a **per-package summarization pass** (one cheap call per top-level package) then a **synthesis pass** that consumes those summaries + the digest to produce the final doc suite. Gate behind `--chunked`/auto-detect by token estimate. *(`generation/chunking.py` (moved from `core/chunking.py`): `group_modules_by_package` + `build_chunked_digest`; auto-triggers when the full digest exceeds `--token-budget`, `--chunked` forces it on regardless of size, per team decision. Cross-package edges are dropped at chunk boundaries — a known, documented simplification.)*
- [x] **2.6** Wrap `LLMClient.complete()` calls with retry/backoff (exponential, jittered) on rate-limit/5xx errors; surface a clear final error after exhausting retries. *(`llm_client._retry_call`.)* Streaming support piped through `rich.Live` remains open — the one deliberately deferred item in this plan, since it's a UX nicety (elapsed-time feedback already exists via the CLI's `rich.status` spinner) rather than a correctness gap.
- [x] **2.7** Add `generation/qa.py` (moved from `core/qa.py`) post-generation pass: regex-extract mermaid blocks and validate structurally (balanced brackets, known diagram keyword); flag internal Markdown links that don't resolve to a file in the same output set; flag leftover `TODO`/`Lorem ipsum`/`{{placeholder}}` patterns. Failures feed into the same repair loop as 2.3 (`pipeline._generate_with_repair` runs QA after structural validation passes and re-prompts on QA failure too).
- [x] **2.8** Make `--model` default come from a resolved provider/model registry with known-good slugs per provider, not a single hardcoded guess in `cli.py`. *(Implemented as `providers/registry.py`'s (moved from `core/providers.py`) `PROVIDER_PRESETS`, covering both native and OpenAI-compatible providers.)*
- [x] **2.9** Add `--max-repair-attempts`, `--token-budget`, `--chunked`, `--yes`/`-y`, `--temperature`, `--max-tokens` CLI passthrough options. *(`LLMClient.complete()` extended with `temperature`/`max_tokens` kwargs, threaded through both `AnthropicClient` and `OpenAIClient`.)*
- [x] **2.10** Tests: a fake `LLMClient` fixture that returns scripted (including deliberately malformed) responses; assert the repair loop recovers a missing-doc-id case; assert QA pass catches a broken Mermaid block and a dead internal link; snapshot test for the full marker-based split. *(`tests/test_pipeline_repair.py`, `tests/test_qa.py`, `tests/test_writer.py`, `tests/test_chunking.py`, `tests/test_pipeline_cost.py` — 85 tests total across the whole suite as of 2026-08-25, all passing.)*
- [x] **2.11** *(Added, not in original scope)* Auto-detect the provider from an `--api-key`'s format (`sk-ant-`, `gsk_`, etc.), fall back to provider-specific env vars, then to a locally running Ollama server, before erroring with concrete free/paid setup guidance. `--provider` is now optional. *(`providers/resolution.py` (moved from `core/provider_resolution.py`), 12 tests in `tests/test_provider_resolution.py`.)*

## Acceptance Criteria

- A response missing one of N expected docs triggers exactly one repair round-trip and succeeds, without the user re-running the command.
- A Markdown horizontal rule (`---`) inside a generated doc body no longer breaks section splitting.
- A deliberately malformed Mermaid block never reaches disk uncorrected.
- Estimated token/cost is shown before any paid API call over the configured threshold.
