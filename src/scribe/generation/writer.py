"""Parses marker-delimited LLM output and writes each named doc to disk.

Sections are matched by an explicit `<!-- SCRIBE:BEGIN doc="X.md" -->` /
`<!-- SCRIBE:END -->` marker pair, not position, so a stray Markdown
horizontal rule or a reordered/omitted document is detected and reported by
name instead of silently corrupting the output.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

_SECTION_PATTERN = re.compile(
    r'<!--\s*SCRIBE:BEGIN\s+doc="(?P<doc_id>[^"]+)"\s*-->(?P<body>.*?)<!--\s*SCRIBE:END\s*-->',
    re.DOTALL,
)


class DocumentCountMismatchError(RuntimeError):
    """Raised when the LLM output doesn't contain the expected sections."""


@dataclass
class ValidationResult:
    """Reports exactly which doc ids are missing/duplicated/extra."""

    found: dict[str, str] = field(default_factory=dict)  # doc_id -> body
    missing: list[str] = field(default_factory=list)
    duplicated: list[str] = field(default_factory=list)
    extra: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.missing and not self.duplicated

    def describe(self) -> str:
        parts = []
        if self.missing:
            parts.append(f"missing: {', '.join(self.missing)}")
        if self.duplicated:
            parts.append(f"duplicated: {', '.join(self.duplicated)}")
        if self.extra:
            parts.append(f"unexpected extra ids: {', '.join(self.extra)}")
        return "; ".join(parts) or "ok"


def parse_sections(markdown: str) -> dict[str, list[str]]:
    """Extract {doc_id: [body, ...]} from marker-delimited `markdown`.

    A list (not a single body) is kept per id so duplicates are detectable.
    """
    sections: dict[str, list[str]] = {}
    for match in _SECTION_PATTERN.finditer(markdown):
        doc_id = match.group("doc_id").strip()
        body = match.group("body").strip()
        sections.setdefault(doc_id, []).append(body)
    return sections


def validate_sections(markdown: str, expected_ids: list[str]) -> ValidationResult:
    """Compare parsed sections against `expected_ids`, reporting by name."""
    parsed = parse_sections(markdown)
    expected_set = set(expected_ids)

    missing = [doc_id for doc_id in expected_ids if doc_id not in parsed]
    duplicated = [doc_id for doc_id, bodies in parsed.items() if len(bodies) > 1 and doc_id in expected_set]
    extra = [doc_id for doc_id in parsed if doc_id not in expected_set]
    found = {doc_id: bodies[0] for doc_id, bodies in parsed.items() if doc_id in expected_set}

    return ValidationResult(found=found, missing=missing, duplicated=duplicated, extra=extra)


def write_documents(documents: dict[str, str], output_dir: Path, doc_ids: list[str]) -> list[Path]:
    """Write each already-validated `{doc_id: body}` entry in `doc_ids` order to `output_dir`.

    `doc_id` may include a folder prefix (e.g. `"user-guides/01-gui.md"` from a dynamic doc
    plan's nested sections); the parent directory is created as needed.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    written_paths: list[Path] = []
    for doc_id in doc_ids:
        file_path = output_dir / doc_id
        file_path.parent.mkdir(parents=True, exist_ok=True)
        file_path.write_text(documents[doc_id] + "\n", encoding="utf-8")
        written_paths.append(file_path)
    return written_paths
