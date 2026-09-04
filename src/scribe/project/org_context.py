"""Optional, user-supplied organizational/infrastructure context that can't be inferred from source.

Real internal documentation often needs facts no static analysis can ever produce: a team
name, a contact address, an internal wiki link, a deployment/environment name, a cloud account
identifier, an on-call process. Scribe never invents any of this -- either the user fills in
`scribe.org.toml` (scaffolded via `scribe org-context`) or generated docs explicitly say the
information wasn't provided, instead of guessing a plausible-sounding but fabricated detail.

Deliberately NOT AWS-specific (or tied to any particular cloud/infra vendor) -- the schema is a
handful of generic named fields plus a freeform `notes` block, so it fits any team/stack.
"""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ImportError:  # Python 3.10
    import tomli as tomllib  # type: ignore[no-redef]

ORG_CONTEXT_FILENAME = "scribe.org.toml"

ORG_CONTEXT_TEMPLATE = '''# S.C.R.I.B.E. organizational context (optional).
#
# Nothing in this file is inferred from your code -- fill in whatever your team wants generated
# docs to reference (contacts, internal links, environment/deployment names, cloud/account
# identifiers, on-call process, etc.). Leave fields blank if not applicable; scribe will never
# invent this information on its own, and generated docs will say so explicitly if a field here
# is left blank or this file doesn't exist.

[org_context]
team_name = ""
contact = ""                  # e.g. an email alias or chat channel
internal_docs_url = ""        # e.g. a wiki/Confluence/Notion space root
deployment_environment = ""   # e.g. "production" / "internal staging" / "on-prem"
notes = """
Add any other org-specific facts here as free text (infra/cloud provider, account or project
ids, on-call process, compliance requirements, etc.) -- whatever your team wants surfaced in
generated docs.
"""
'''


def org_context_path(repo_path: Path) -> Path:
    return repo_path / ORG_CONTEXT_FILENAME


def write_org_context_template(repo_path: Path) -> Path:
    """Scaffold `scribe.org.toml` if it doesn't already exist. Never overwrites."""
    path = org_context_path(repo_path)
    if not path.exists():
        path.write_text(ORG_CONTEXT_TEMPLATE, encoding="utf-8")
    return path


def load_org_context(repo_path: Path) -> str:
    """Render `scribe.org.toml` as prompt text, or an explicit "not provided" instruction.

    The explicit "don't invent this" instruction is returned (not an empty string) whenever
    there's nothing real to say, so the generation prompt always has a clear, unambiguous
    instruction here rather than a silent gap the model might feel invited to fill in.
    """
    path = org_context_path(repo_path)
    if not path.exists():
        return (
            "No organizational/infrastructure context file was provided "
            f"({ORG_CONTEXT_FILENAME} not found -- run `scribe org-context` to scaffold one). "
            "Do NOT invent a company/team name, account identifiers, contact details, "
            "environment names, or other org-specific facts -- describe things generically, or "
            "note that this should be filled in by the team."
        )

    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return (
            f"{ORG_CONTEXT_FILENAME} exists but couldn't be read/parsed -- treat organizational "
            "context as unavailable and do not invent it."
        )

    fields = data.get("org_context", {})
    filled = {k: v.strip() for k, v in fields.items() if isinstance(v, str) and v.strip()}
    if not filled:
        return (
            f"{ORG_CONTEXT_FILENAME} exists but has no fields filled in -- treat organizational "
            "context as unavailable and do not invent it."
        )

    lines = [
        "The following organizational/infrastructure context was explicitly provided by the "
        "team -- use it freely, but do not add anything beyond it:"
    ]
    lines += [f"- {key}: {value}" for key, value in filled.items()]
    return "\n".join(lines)
