"""Tests for optional, user-supplied organizational/infra context (`project/org_context.py`).

Scribe must never invent a company name, contact, account id, or environment name -- these
tests specifically check the "not provided" case produces an explicit instruction not to guess,
not silence.
"""

from __future__ import annotations

from scribe.project.org_context import (
    ORG_CONTEXT_FILENAME,
    load_org_context,
    org_context_path,
    write_org_context_template,
)


def test_load_org_context_when_file_absent_says_so_explicitly(tmp_path):
    text = load_org_context(tmp_path)
    assert ORG_CONTEXT_FILENAME in text
    assert "do not invent" in text.lower() or "not invent" in text.lower()


def test_write_org_context_template_creates_file(tmp_path):
    path = write_org_context_template(tmp_path)
    assert path == org_context_path(tmp_path)
    assert path.exists()
    assert "[org_context]" in path.read_text(encoding="utf-8")


def test_write_org_context_template_never_overwrites_existing_file(tmp_path):
    path = org_context_path(tmp_path)
    path.write_text('# hand-edited, do not touch\n[org_context]\nteam_name = "Platform"\n', encoding="utf-8")

    write_org_context_template(tmp_path)

    assert "hand-edited" in path.read_text(encoding="utf-8")


def test_load_org_context_renders_filled_fields(tmp_path):
    path = org_context_path(tmp_path)
    path.write_text(
        '[org_context]\nteam_name = "Platform"\ncontact = "platform@example.com"\n',
        encoding="utf-8",
    )

    text = load_org_context(tmp_path)

    assert "Platform" in text
    assert "platform@example.com" in text
    assert "do not invent" not in text.lower()


def test_load_org_context_treats_all_blank_fields_as_unavailable(tmp_path):
    path = org_context_path(tmp_path)
    path.write_text('[org_context]\nteam_name = ""\ncontact = ""\n', encoding="utf-8")

    text = load_org_context(tmp_path)

    assert "do not invent" in text.lower()


def test_load_org_context_handles_malformed_toml_gracefully(tmp_path):
    path = org_context_path(tmp_path)
    path.write_text("this is not valid toml [[[", encoding="utf-8")

    text = load_org_context(tmp_path)

    assert "couldn't be read/parsed" in text or "unavailable" in text.lower()
