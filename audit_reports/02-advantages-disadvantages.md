# 02 — Advantages vs. Disadvantages

Weighed, not just listed — each item states why it matters, not just that it exists.

## Advantages

| # | Advantage | Why it actually matters |
|---|---|---|
| 1 | Clean separation of concerns (extract / prompt / LLM / write / QA, each independently testable) | Changes to one stage (e.g. swapping the digest algorithm) can't silently break another; proven by 85 tests with zero real network/subprocess calls |
| 2 | Real, verified Graphifyy integration, including a discovered real failure mode fixed (`--code-only`) | The riskiest external dependency in the project was de-risked by actually running it, not by reading its README and assuming |
| 3 | Graceful degradation at every layer | No single missing piece (Graphifyy, an API key, a local model) produces a hard crash — always a fallback or an actionable message |
| 4 | Multi-provider support including genuinely free/local options (Ollama, Groq free tier) | Removes cost as a barrier to adoption for a 3-person team; most competing tools assume a paid API key |
| 5 | Incremental regeneration via content-hash manifest | The concrete, measurable claim ("unchanged repo = instant no-op, zero LLM spend") that differentiates this from "flatten and re-ask" tools |
| 6 | Self-correcting project documentation (`plans/`) | Checkboxes were caught and fixed mid-session when they drifted from reality — this is a project that audits its own claims, a genuinely rare discipline |
| 7 | No bare `except Exception` anywhere in the CLI | Every failure mode has a named exception and a tailored message; failures are legible, not mysterious |
| 8 | *(Added 2026-08-25)* Graphifyy "not installed" vs. "installed but failed" are handled as genuinely different recovery paths, not one generic fallback | Matches how an engineer would actually want to be asked -- offer to install-and-retry when it's just missing, but show the manual command and let the user investigate a real failure before silently degrading quality | 

## Disadvantages

| # | Disadvantage | Why it actually matters | Severity |
|---|---|---|---|
| 1 | Zero real-LLM verification (see report 01) | The core value proposition — "the generated docs are good" — is the one thing never observed | **Critical** |
| 2 | No CI yet (Plan 04 incomplete: no `.github/workflows/`, no coverage gate) | Every "85 tests pass" claim this session required a human to remember to run pytest; nothing enforces it on the next change | High |
| 3 | No packaging/distribution (Plan 05 not started) | Contradicts the team's own stated need (C++/C#/Unreal engineers without a Python-first setup) — today, using this tool still requires `pip` and Python literacy | High |
| 4 | Native fallback's non-Python extraction is regex-based, not AST-based | This directly affects the team's *own* primary codebases (C++/C#/Unreal) if Graphifyy isn't installed — the fallback is weakest exactly where this team would use it most | High |
| 5 | Rigid, hardcoded doc-suite structure (`constants.py`) | Every team gets exactly the same 4 or 8 documents; no way to add/remove/rename a section without editing source | Medium |
| 6 | Confidence signal (`EXTRACTED`/`INFERRED`/`AMBIGUOUS`) from Graphifyy is discarded during aggregation | A real, already-available signal for "how sure are we about this architectural claim" is thrown away before it ever reaches the prompt | Medium |
| 7 | Cross-package edges dropped at chunk boundaries in map-reduce mode | Large-repo documentation via chunking is measurably lossier than small-repo documentation — undocumented to the end user beyond a code comment | Medium |
| 8 | No template/prompt customization | One master prompt, one voice, for every team that adopts this — a real limitation for a tool positioned as complementary/flexible internal tooling | Medium |
| 9 | All verification this session was on Windows only | "Designed to be OS-agnostic" (correct `pathlib` usage, conditional `.exe` handling) is not the same claim as "proven to work on Linux/macOS" — see report 03 | Medium |
| 10 | No versioning discipline yet (`version = "0.1.0"` static, no `CHANGELOG.md`) | Nothing currently distinguishes "the version from last week" from "the version from today" if this gets distributed at all | Low |
| 11 | *(Added 2026-08-25)* `tests/test_cli.py`'s `CliRunner` invocations of `generate` don't pass an isolated `--cache-dir`, so they write into the real, default `~/.scribe_cache` on whatever machine runs them | Confirmed by inspecting the real cache directory on this machine: dozens of near-empty (`file_count: 0`) cached entries that can only have come from test runs, not real usage -- every dev/CI machine accumulates test pollution in its actual cache directory, run after run | Medium |

## Net Assessment

The engineering quality of what exists is genuinely strong for a project this size — better
error handling, test discipline, and self-correction than most internal tools this small ever
get. But the disadvantages are concentrated exactly where they're most costly: the one thing
never verified (real LLM output quality) is the entire reason the tool exists, and the one
audience most under-served by the current fallback (C++/C#/Unreal engineers without Graphifyy)
is the team's own primary domain. Neither is a reason to distrust the engineering — both are
reasons to prioritize closing them before adding more surface area.

**2026-08-25 update:** this net assessment is unchanged. The session's own newest work (the
Graphifyy install/failure UX, advantage #8) is more evidence of the same pattern named above —
genuinely good engineering, added to a part of the pipeline (extraction) that was never the
unverified part in the first place. Disadvantage #1 is still the one that matters most, and it's
still untouched.
