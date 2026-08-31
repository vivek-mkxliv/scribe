# Plan 05 — Packaging & Distribution

**Goal:** get S.C.R.I.B.E. into the hands of engineers who won't `pip install` anything — this is an ADAS/simulation team with C++/C#/Unreal engineers, not a Python shop.

## Current State

The only installation path is `pip install -e .` from a cloned repo inside a manually created venv. There's no `LICENSE` file, no PyPI publish process, no standalone executable, and no integration with the editors/tools the rest of the team actually lives in.

## Goals

1. Publish proper, versioned releases (PyPI at minimum).
2. Ship standalone binaries so non-Python engineers can run `scribe.exe generate` with no environment setup.
3. Make it trivially invocable from VS Code (task or thin extension command) since that's the team's primary editor.
4. Add a `LICENSE` and versioning/release process before this goes any further.

## Tasks

- [ ] **5.1** Choose and add a `LICENSE` file (confirm with whoever owns IP policy at the parent company before defaulting to MIT/Apache-2.0 — internal tools sometimes need a different stance).
- [ ] **5.2** Add semantic versioning discipline: bump `version` in `pyproject.toml` per release, add `CHANGELOG.md` (Keep a Changelog format), tag releases in git.
- [ ] **5.3** Add `.github/workflows/release.yml`: on tag push, build the wheel/sdist and publish to PyPI (or an internal package index if public PyPI isn't appropriate for a corporate tool) using trusted publishing / an API token secret.
- [ ] **5.4** Add PyInstaller build steps (`--onefile`) for Windows/Linux/macOS producing a `scribe` binary attached to GitHub Releases, so engineers without a Python toolchain can drop it on PATH and go. Verify the bundled binary still works with the `anthropic`/`openai` optional extras baked in (or document that API-key-based cloud calls still need network access regardless).
- [ ] **5.5** Add a `.vscode/tasks.json` snippet (shipped in the repo, documented in the README) that runs `scribe generate` as a VS Code task with sensible defaults, so it's one command-palette action away without touching a terminal.
- [ ] **5.6** (Stretch) Scaffold a minimal VS Code extension (`vscode-scribe`) exposing a "S.C.R.I.B.E.: Generate Docs" command and a status-bar entry showing drift status (green/red based on `scribe generate --check`), reusing the CLI as a subprocess rather than reimplementing logic.
- [ ] **5.7** Add a `Dockerfile` (and optionally a devcontainer) so CI runners and engineers on locked-down machines can run S.C.R.I.B.E. without any local Python install at all.
- [ ] **5.8** Verify install instructions in the README work on a genuinely clean machine/VM before calling this plan done — don't just assume `pip install -e .` generalizes.

## Acceptance Criteria

- A team member with no Python installed can download a release asset and run `scribe generate` successfully on Windows.
- A tagged git push produces a published PyPI release and attached platform binaries automatically, with no manual steps.
- `scribe generate` is reachable from the VS Code command palette in this repo without opening a terminal.
