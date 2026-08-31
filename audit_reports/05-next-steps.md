# 05 — Next Steps

Ordered by priority, with the reasoning for the order made explicit — not just a restatement of
`plans/README.md`'s roadmap, though it agrees with it.

> **Refreshed 2026-08-25.** The ordering below is unchanged from the original pass — the one
> new item this refresh found (#3a, test cache-dir pollution) slots into P1 alongside the other
> Plan 04 gaps; it doesn't change what P0 is. If you're returning to this list after a break: P0
> is still not done, and everything built in between (the Graphifyy install/failure UX) landed
> without it being done, which is worth noticing, not just noting — see
> `unbiased_judjement.md`'s 2026-08-25 addendum.

## P0 — Do This Before Anything Else

1. **Run one real, end-to-end generation against a real LLM provider.** Every other finding in
   this audit is downstream of this being unverified. Pick one path (a paid key, or Ollama
   running locally — both already fully wired and tested up to the point of the actual API call)
   and generate real docs for a real repo. This validates or invalidates the entire premise
   before any more feature work is justified.
2. **Read the output critically, as if reviewing a junior engineer's first PR.** Specifically
   check: did the repair loop ever trigger, did QA ever flag something, does the Dev
   Playbook/Dev Docs section actually match the real architecture, and how did the tone differ
   across at least two different providers (e.g., Anthropic vs. a free Groq/Ollama model) if you
   try both.

## P1 — Close the Gaps This Audit Found

3. **Add the OS matrix to CI** (`plans/04` task 4.5, `ubuntu-latest`/`windows-latest`/
   `macos-latest`) — the single cheapest fix that converts report 03's "designed to be
   cross-platform" into "verified to be cross-platform," and it was already on the roadmap.
3a. *(Added 2026-08-25)* **Fix `tests/test_cli.py`'s cache-dir pollution** (`plans/04` task 4.9,
   report 02's disadvantage #11) before wiring up CI — an isolated `--cache-dir`/fixture is a
   small, contained fix and CI runners shouldn't inherit a habit of writing into a real user
   cache directory.
4. **Stop discarding Graphifyy's confidence tags** (future-suggestions #1) — the data is already
   being computed and thrown away; this is a small, contained change to
   `parse_graphifyy_output`/`DependencyEdge`, not a new subsystem.
5. **Finish Plan 04**: coverage gate (`pytest-cov`), the `.github/workflows/ci.yml` itself, and
   pre-commit config. Nothing currently *enforces* that the next change keeps 85/85 tests
   passing — that has been a human running commands manually all session.

## P2 — Decisions That Need You, Not More Engineering

6. **Answer Plan 05's blocking question**: license and distribution channel (public PyPI vs.
   internal package index vs. binary-only). Packaging work cannot proceed without this, and it's
   been an open question since Plan 05 was written.
7. **Decide on doc-suite/template configurability** (future-suggestions tier 2, item 4): is the rigid
   4-doc/8-doc structure acceptable long-term, or does this need to become configurable before
   it's used on a second repo? This changes the shape of `constants.py` and the prompt template
   meaningfully, so it's worth deciding deliberately rather than organically.

## P2 — Then Resume the Roadmap in Order

8. **Plan 05** (packaging): PyInstaller binaries, VS Code task, `CHANGELOG.md`/versioning — once
   #6 is answered. This is what actually gets the tool in front of the C++/C#/Unreal engineers on
   the team who won't `pip install` anything, which is the whole stated point of Plan 05.
9. **Plan 06** (adoption): dogfood the docs (`scribe generate` on this repo, commit the output),
   rewrite the README as a pitch, write `CONTRIBUTING.md`. Deliberately last — dogfooding before
   step 1 above would mean shipping unverified output as "proof it works."

## P3 — Worth Scheduling, Not Urgent

10. Close the remaining future-suggestions items (tier 1 item 3's chunking/caching work, tier 2's
    tree-sitter second-tier fallback for the team's own C++/C#/Unreal stacks, and the hand-edit
    learning idea) as the tool sees real usage and it becomes clear which of them actually matter
    in practice —
    don't build all of report 04 speculatively before there's real usage data to prioritize by.
