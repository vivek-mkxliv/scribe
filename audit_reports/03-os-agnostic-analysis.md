# 03 — OS-Agnostic Analysis

**Verdict: written to be cross-platform (correctly, in most places), but only *run and
verified* on Windows this entire session.** These are two different claims — the code below
supports the first; nothing in this repo yet supports the second.

## Evidence For (the code itself is careful)

| Concern | How it's handled | File |
|---|---|---|
| Path construction | `pathlib.Path` used throughout; no manual string concatenation with `/` or `\` for filesystem paths | Every module |
| Executable name differences | `("graphify.exe", "graphify") if os.name == "nt" else ("graphify",)` — explicit branch, not an assumption | `extraction/extractor.py::_find_graphify_executable` |
| No shell-specific quoting risk | Every `subprocess.run()` call passes an argument list, never `shell=True` with a hand-built command string | `extraction/extractor.py`, `extraction/gitutil.py` |
| Directory walking | `os.walk(..., followlinks=False)` — cross-platform, and symlink-safe on both POSIX and Windows | `extraction/scan_config.py` |
| Config parsing | `tomllib` (3.11+) / `tomli` (3.10) — pure Python, no platform dependency | `project/config_loader.py` |
| Local-model detection | `urllib.request` HTTP call to `localhost` — no OS-specific networking | `providers/resolution.py` |
| Cache/output locations | `Path.home() / ".scribe_cache"` — resolves correctly on both Windows (`C:\Users\<user>`) and POSIX (`/home/<user>`) | `extraction/cache.py` |
| Console entry point | Declared via `[project.scripts]` in `pyproject.toml` — `pip` generates the correct wrapper (`.exe` shim on Windows, plain script on POSIX) per platform at install time | `pyproject.toml` |
| Repo-relative paths in output | Deliberately normalized to forward slashes via `.as_posix()` before being written into generated docs/graph data | `extraction/extractor.py`, `extraction/models.py` |

This is meaningfully better than "happens to work" — the `os.name` branch and the
interpreter-relative executable lookup in particular reflect an engineer who thought about
*why* a Windows-vs-POSIX difference would matter, not just copy-pasted a pattern.

## Evidence Against / Untested Territory

1. **Every single command run this session was PowerShell on Windows.** There is no CI, so
   there is no automated evidence this codebase has ever executed on Linux or macOS. "Uses
   `pathlib` correctly" is necessary but not sufficient — real-world cross-platform bugs live in
   the 5% of edge cases (case-sensitive filesystems, path length limits, line-ending handling,
   permission models) that reading the code doesn't surface.
2. **Symlink handling is asymmetric in practice, even if the code is uniform.** `followlinks=False`
   behaves identically on both OSes at the API level, but symlinks are far more common in typical
   POSIX repos (and require elevated privileges/Developer Mode to even create on Windows) — so
   this code path has effectively never been exercised in this session's testing.
3. **`git`/`graphify` are assumed to be on `PATH` for their respective subprocess calls** — true
   cross-platform, but the *install experience* of getting them there differs a lot by OS (this
   is a Plan 05 packaging concern, not a bug, but it means "OS-agnostic code" and "OS-agnostic
   installation experience" are two different bars, and only the first is currently met).
4. **No `os`/`sys.platform` guard exists anywhere for line-ending differences** in generated
   Markdown files — unlikely to cause a real bug (`Path.write_text` normalizes per-platform via
   Python's universal newline handling by default), but it's untested, not verified-safe.

## Recommendation

This is the single cheapest, highest-leverage fix available: **Plan 04's task 4.5 already calls
for a GitHub Actions matrix** (`ubuntu-latest`, `windows-latest`, `macos-latest`). That one CI
file converts every claim in this report from "the code looks portable" into "80 tests actually
pass on all three OSes, continuously." Until that exists, treat "OS-agnostic" as a design intent
that has been engineered for, not a verified property of this codebase.

**2026-08-25 re-check:** unchanged. This session's new work (the Graphifyy install/failure UX)
was again exercised only on Windows, in the same PowerShell environment as everything before it —
the `os.name == "nt"` branch in `_find_graphify_executable()` and the new `sys.stdin.isatty()`
interactivity gate in `cli.py` are both written to be cross-platform-correct, but neither has been
run on Linux/macOS this session either. The recommendation below is still open and still the
right next step.
