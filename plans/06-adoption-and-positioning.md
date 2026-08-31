# Plan 06 — Adoption & Positioning

**Goal:** make the README and surrounding materials do the selling — a lean three-person team's tool survives on being obviously better than the alternative, not on a mandate.

## Current State

[`README.md`](../README.md) is a four-section quick-start with no positioning, no visuals, no comparison to the tools it's meant to replace (Repomix-style flattening, hand-written wikis, or "just read the parent company's enterprise simulator docs"), no `CONTRIBUTING.md`, no `LICENSE` (tracked in Plan 05), and the tool has never been run on itself — there's no `/docs` output to point to as proof.

## Goals

1. Reposition the README as a pitch: what problem this solves, why it's not competing with the parent company's enterprise simulators, and proof it works.
2. Dogfood: generate S.C.R.I.B.E.'s own documentation with S.C.R.I.B.E. and commit it.
3. Give contributors (even just the two other engineers) a clear, low-friction path to add to the project.
4. Produce a demo artifact (recorded terminal session or GIF) — text descriptions of a CLI tool undersell it.

## Tasks

- [ ] **6.1** Rewrite `README.md` with: a one-paragraph problem statement, a "why not Repomix / why not the enterprise simulator" comparison table, an architecture Mermaid diagram of S.C.R.I.B.E. itself, and the existing quick-start tightened to the config-file-driven flow from Plan 03.
- [ ] **6.2** Run `scribe generate --mode lean_technical` against this repo once Plans 01–04 land, and commit the output under `/docs` — this becomes the tool's own proof-of-quality artifact and should be linked prominently from the README.
- [ ] **6.3** Add `CONTRIBUTING.md`: how to set up a dev env, run tests (link to Plan 04), coding conventions, and the PR checklist (tests pass, `scribe generate --check` clean).
- [ ] **6.4** Add `CODE_OF_CONDUCT.md` only if this becomes externally visible/open-source; skip if it stays an internal tool — confirm with the team before adding boilerplate that doesn't fit a 3-person internal project.
- [ ] **6.5** Record a short terminal demo (asciinema or a GIF via `vhs`/`terminalizer`) showing `scribe init` → `scribe generate` → opening the resulting docs, embed it in the README.
- [ ] **6.6** Write a one-page internal positioning note (separate from the README) aimed at the parent company stakeholders: explicitly frame S.C.R.I.B.E. as complementary tooling that keeps local/rapid-prototyping documentation in sync without competing with or duplicating the enterprise simulator's own documentation systems. This directly answers the "why does a 3-person team need its own tool" question before it's asked.
- [ ] **6.7** Add badges (build status from Plan 04's CI, PyPI version from Plan 05, license) to the top of the README once those pipelines exist — don't add placeholder badges before they're real.

## Acceptance Criteria

- A new engineer can read the README top-to-bottom and understand what problem this solves and why it exists alongside the parent company's tooling, in under two minutes.
- `/docs` in this repo is real S.C.R.I.B.E. output, not hand-written.
- A demo artifact exists and is linked from the README.
