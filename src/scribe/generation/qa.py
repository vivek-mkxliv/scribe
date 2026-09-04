"""Post-generation quality checks run before docs are written to disk.

Catches the failure modes an LLM is most likely to introduce in generated
documentation: unbalanced/invalid Mermaid blocks, dead intra-suite links,
and leftover placeholder text.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

_MERMAID_BLOCK_PATTERN = re.compile(r"```mermaid\s*\n(.*?)```", re.DOTALL)
_INTERNAL_LINK_PATTERN = re.compile(r"\[[^\]]+\]\((?!https?://|mailto:)([^)#]+)")
_PLACEHOLDER_PATTERNS = (
    re.compile(r"\bTODO\b", re.IGNORECASE),
    re.compile(r"\bLorem ipsum\b", re.IGNORECASE),
    re.compile(r"\{\{[^}]+\}\}"),
    re.compile(r"\[INSERT[^\]]*\]", re.IGNORECASE),
)
_KNOWN_MERMAID_DIAGRAM_TYPES = (
    "flowchart",
    "graph",
    "sequenceDiagram",
    "classDiagram",
    "stateDiagram",
    "erDiagram",
    "gantt",
    "pie",
    "journey",
    "mindmap",
    "timeline",
)
# A block consisting only of style/legend directives is a real (if non-standard) pattern some
# models produce as a follow-up to a diagram block rather than inline -- not a broken diagram.
_STYLE_ONLY_PREFIXES = ("classDef", "style", "linkStyle", "click")


@dataclass
class QAIssue:
    doc_id: str
    category: str  # "mermaid" | "dead_link" | "placeholder"
    message: str
    target: str | None = None  # the raw link target, for dead_link issues only


@dataclass
class QAReport:
    issues: list[QAIssue] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.issues

    def describe(self) -> str:
        return "; ".join(f"[{issue.doc_id}] {issue.category}: {issue.message}" for issue in self.issues)


def _check_mermaid_blocks(doc_id: str, body: str) -> list[QAIssue]:
    issues = []
    for block in _MERMAID_BLOCK_PATTERN.findall(body):
        stripped = block.strip()
        if not stripped:
            issues.append(QAIssue(doc_id, "mermaid", "Empty mermaid code block."))
            continue
        first_line = stripped.splitlines()[0].strip()
        recognized = any(first_line.startswith(kind) for kind in _KNOWN_MERMAID_DIAGRAM_TYPES)
        style_only = any(first_line.startswith(prefix) for prefix in _STYLE_ONLY_PREFIXES)
        if not recognized and not style_only:
            issues.append(
                QAIssue(doc_id, "mermaid", f"Unrecognized diagram type on first line: {first_line!r}")
            )
        if stripped.count("[") != stripped.count("]") or stripped.count("(") != stripped.count(")"):
            issues.append(QAIssue(doc_id, "mermaid", "Unbalanced brackets/parentheses in diagram."))
    return issues


def _check_dead_internal_links(doc_id: str, body: str, known_basenames: set[str]) -> list[QAIssue]:
    issues = []
    for target in _INTERNAL_LINK_PATTERN.findall(body):
        target_name = target.split("/")[-1].lstrip("./")
        if target_name.endswith(".md") and target_name not in known_basenames:
            issues.append(
                QAIssue(
                    doc_id,
                    "dead_link",
                    f"Links to {target_name!r}, which is not in this suite.",
                    target=target_name,
                )
            )
    return issues


def _check_placeholders(doc_id: str, body: str) -> list[QAIssue]:
    issues = []
    for pattern in _PLACEHOLDER_PATTERNS:
        match = pattern.search(body)
        if match:
            issues.append(QAIssue(doc_id, "placeholder", f"Leftover placeholder text: {match.group(0)!r}"))
    return issues


def review_documents(documents: dict[str, str], known_doc_ids: set[str] | None = None) -> QAReport:
    """Run all QA checks over `{doc_id: body}` and return a combined report.

    `known_doc_ids` is the full set of doc ids valid for cross-linking (the whole doc plan) --
    NOT just the documents passed in this call. Per-page generation calls this with only one
    document at a time, so defaulting to `set(documents)` would flag every cross-link to a
    sibling page as dead; callers generating a subset of a larger suite must pass the full set
    explicitly. Matching is by basename on both sides, so a correctly nested-folder cross-link
    (e.g. `../user-guide/01-execution.md` linking to known id `user-guide/01-execution.md`)
    resolves without needing full relative-path resolution.
    """
    known_doc_ids = known_doc_ids if known_doc_ids is not None else set(documents)
    known_basenames = {known_id.split("/")[-1] for known_id in known_doc_ids}
    issues: list[QAIssue] = []
    for doc_id, body in documents.items():
        issues.extend(_check_mermaid_blocks(doc_id, body))
        issues.extend(_check_dead_internal_links(doc_id, body, known_basenames))
        issues.extend(_check_placeholders(doc_id, body))
    return QAReport(issues=issues)
