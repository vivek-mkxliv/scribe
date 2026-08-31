# S.C.R.I.B.E. — Independent Audit

**Auditor stance:** senior software engineer / senior Python developer / software architect / AI-ML practitioner, reviewing the codebase as it exists on disk plus the full `plans/` roadmap — not the aspirational pitch.

**Scope reviewed:** `src/scribe/` (26 source files across `cli.py`/`config.py`/`constants.py`/`pipeline.py` + the `extraction/`, `providers/`, `generation/`, `project/` packages, ~2,065 LOC), `tests/` (12 files, ~851 LOC, 85 passing tests), `pyproject.toml`, `plans/01`–`06`, `README.md`, `MODELS.md`, `docs/GRAPHIFYY_CONTRACT.md`.

**Last refreshed:** 2026-08-25. Since the original pass, the codebase was restructured (`core/` split into 4 domain packages) and a new interactive Graphifyy install/failure-recovery flow was added to `extractor.py`/`pipeline.py`/`cli.py` (+5 tests, 80 → 85 total). Every finding below was re-verified against the current tree, not copy-forwarded from the prior pass — where something changed, it says so explicitly; where it didn't, the original wording stands.

## Reports in This Folder

| File | Covers |
|---|---|
| [01-feasibility-novelty-usability.md](01-feasibility-novelty-usability.md) | Is this achievable, is it actually new, is it pleasant to use |
| [02-advantages-disadvantages.md](02-advantages-disadvantages.md) | Weighed pros/cons, not a marketing list |
| [03-os-agnostic-analysis.md](03-os-agnostic-analysis.md) | Is it actually cross-platform, or just written to look that way |
| [04-future-suggestions-intelligence-and-agnosticism.md](04-future-suggestions-intelligence-and-agnosticism.md) | Concrete ideas to make it smarter and less hardcoded to this one repo |
| [05-next-steps.md](05-next-steps.md) | Prioritized action list |

## Headline Finding (read this even if nothing else)

**The single largest unverified assumption in the entire project, after 6 plans and 85 passing tests, is that the LLM actually produces good documentation.** Every test in this repo uses a scripted `FakeLLMClient` — for good reason (deterministic, free, fast CI) — but that means the core value proposition ("an LLM + a knowledge graph produces professional docs") has never once been observed against a real model. Everything else audited below is sound engineering built on top of that one unverified premise. See [05-next-steps.md](05-next-steps.md) — closing this gap is next-step #1, ahead of any further feature work.

**This still holds true as of the 2026-08-25 refresh.** The work done since the original audit (package restructuring, the Graphifyy install/failure-handling UX) added real, well-tested capability but did not touch this gap either way — it's neither closed nor made worse, just unaddressed for one more round of feature work. See `unbiased_judjement.md`'s appended 2026-08-25 note for the pattern this represents.
