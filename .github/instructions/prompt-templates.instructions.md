---
description: "Guardrails for editing scribe's LLM prompt templates (master_prompt.md, planning_prompt.md, revision_prompt.md). Use when writing or reviewing prompt template changes, adding new format requirements, or changing QA-relevant instructions."
applyTo: "src/scribe/templates/**"
---

# Prompt Template Guardrails

These templates are the primary defense against a code-to-documentation tool producing
confidently wrong output. When editing any template here, preserve (don't weaken) these rules
added 2026-09-04 after live runs found hallucinated CLI flags, thin generic content, and
contradictory claims across pages of the same generated suite:

1. **Anti-hallucination is absolute.** Every concrete noun (command, flag, file path,
   function/class name, config key) must trace to the Project Context / Knowledge Graph /
   Detected CLI Surface actually injected into the prompt. Never let a template imply it's OK to
   fill a gap with a "plausible" invented detail.
2. **Unknowns must be stated, not filled.** When grounding is missing, the instruction must tell
   the model to say so explicitly ("not derivable from static analysis") rather than guess or
   cross-reference outside knowledge.
3. **Every generated page ends with `## References`** listing every real file/module/flag it
   cited — this is what makes claims auditable after the fact.
4. **Diagrams need prose, not just Mermaid.** Any required diagram must be accompanied by an
   explanation of what it shows, citing the real modules behind each node — a diagram alone is a
   picture, not documentation.
5. **Thinness bar is concrete.** "Don't stop at one sentence" must be paired with a specific
   target (cite 2-3 real identifiers per section) — vague "be thorough" language gets ignored by
   smaller local models in practice.
6. **Doc-structure page counts must never be symmetric for its own sake.** `planning_prompt.md`
   and `revision_prompt.md` both require a self-audit checklist (devil's-advocate questions)
   resolved BEFORE the model emits JSON — keep this as a single-call instruction, not a second
   LLM roundtrip (see `.github/instructions/testing.instructions.md` on `call_count` tests).
7. **Cross-linking covers prose, not just Markdown links.** A dangling "see the X guide" with no
   such page in the plan is exactly as misleading as a dead link — both must be banned.

If you add a new format requirement, also consider whether `generation/qa.py` should gain a
matching automated check (see `_check_flag_grounding` for the precedent: QA validates what the
prompt asks for, since local models don't reliably follow prompt-only instructions).
