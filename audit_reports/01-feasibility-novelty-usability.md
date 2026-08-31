# 01 — Feasibility, Novelty, Usability

## Feasibility

**Technical feasibility: high, and largely already demonstrated.** The pipeline
(extract → assemble → generate → validate/repair → write) is architecturally simple, each
stage is a pure function or small class, and the hard integration risk (Graphifyy's real CLI
contract) has been retired — not assumed, actually verified against the real tool, including
discovering and fixing a real failure mode (`--code-only` to avoid a second, hidden LLM-key
requirement). That kind of "verify, don't assume" work is the difference between a feasibility
study and a working system, and it's already done for the extraction half of the pipeline.

**What is NOT yet demonstrated:** a real LLM call, end to end. Every test uses `FakeLLMClient`.
The repair loop, the QA gate, the chunking map-reduce path — all logic-tested against scripted
responses, never against what an actual model returns. This is not a flaw in the testing
strategy (mocking the LLM is correct practice for a deterministic, free, fast test suite) — but
it does mean **feasibility of the actual documentation-quality promise is unverified**, not just
untested. A model could:
- Ignore the marker contract more often than the repair loop's default 2 retries can absorb.
- Produce structurally valid, QA-clean docs that are nonetheless architecturally wrong (QA
  checks Mermaid syntax and dead links, not factual accuracy against the graph).
- Behave differently across the many supported providers (Anthropic vs. a small Ollama model
  vs. a free-tier Groq model) — the multi-provider flexibility is a real strength, but it also
  multiplies the number of "does this actually produce good docs" combinations to validate.

**Organizational feasibility:** realistic for a 3-person team at the current size (~2,700 LOC
across source+tests). The roadmap discipline (`plans/`, checkbox-tracked, self-correcting when
stale) is unusually good hygiene for a project this size — that itself is a feasibility positive,
since it means scope and state are legible to whoever picks this up next, not just tribal
knowledge.

## Novelty

**Moderate, and concentrated in execution quality rather than the core idea.** "LLM + code
knowledge graph instead of flattening the repo" is an active space (GraphRAG-style approaches,
several commercial and OSS tools converging on the same idea) — the core idea is not new.

What *is* genuinely well-done relative to the field:
- **Confidence-tagged extraction (`EXTRACTED`/`INFERRED`/`AMBIGUOUS`) exists in the underlying
  Graphifyy graph but is currently discarded** when scribe aggregates to file-level edges (see
  `parse_graphifyy_output` in `extractor.py`). This is a missed novelty opportunity, not a
  realized one yet — flagged again in report 04.
- **Audience-split documentation** (`operator_split`'s strict operator/engineer separation) is a
  reasonable product framing but is a prompt-engineering choice, not a technical innovation.
- **Multi-provider auto-detection from API key shape** (`sk-ant-` → Anthropic, `gsk_` → Groq,
  etc.) is a small but genuinely useful piece of novel UX — most CLI tools in this space make you
  specify the provider explicitly.
- **Incremental regeneration via content-hash manifest** is the most defensible "actually better
  than the obvious competitor" claim (Repomix-style tools re-flatten and re-ask every time; this
  tool skips the entire pipeline, no LLM call at all, when nothing changed).

## Usability

**Real strengths, verified in this session, not just claimed:**
- Zero-to-first-run friction is low: `scribe init` → `scribe generate`, or just
  `scribe generate --api-key ...` with auto-detection.
- Graceful degradation is thorough: missing Graphifyy → native fallback with a warning, missing
  API key → concrete free/paid setup guidance (not a stack trace), oversized repo → auto-chunk or
  a confirmable cost warning, existing docs → overwrite confirmation only when scribe doesn't
  already own them.
- `--dry-run`, `--check`, `--verbose`/`--quiet` cover the "let me see what this would do without
  committing" and "make this safe for CI" use cases well.

**Real gaps:**
- No GUI, no VS Code integration yet (Plan 05 not started) — for an ADAS team with C++/C#/Unreal
  engineers who may not live in a terminal, "usable" currently still means "comfortable with a
  CLI and Python packaging," which is a real subset of the stated target audience.
- The 4-doc/8-doc suite structure is rigid — no way to add a 5th document or rename one without
  editing `constants.py` and the master prompt template. For a tool whose entire pitch is
  flexibility versus rigid enterprise tooling, this is a notable inconsistency.
- No template customization — every team gets the same voice/structure; there's no override
  mechanism for a team that wants different section headers or a different tone.

## Addendum, 2026-08-25 — Graphifyy install/failure UX

Since the original pass, `graphifyy` (0.9.48) was actually installed into this project's own dev
environment, and the extraction layer gained a genuinely useful usability improvement: it now
distinguishes "Graphifyy isn't installed" (offers to `pip install` it and retry once) from
"Graphifyy is installed but a real run of it failed" (shows the failure detail and the exact
manual command, then asks whether to continue with the fallback or abort). Both are gated to
interactive-only sessions (`--quiet`/`--yes`/non-TTY still fall back silently, matching the
existing cost/overwrite confirmation pattern), and the behavior is covered by 5 new unit tests
that exercise the real `extract_context()` logic, not just the callback contracts in isolation.

This is real, verified feasibility/usability progress on the extraction side specifically. It
does **not** change the feasibility verdict above about the *documentation-quality* promise —
that remains entirely about what happens after extraction, at the LLM call, which this addendum
doesn't touch. Worth naming explicitly: this is the kind of "more breadth before the central
premise is validated" pattern flagged in `unbiased_judjement.md`'s original critique, happening
again in this same session — see that file's 2026-08-25 addendum for the direct discussion.
