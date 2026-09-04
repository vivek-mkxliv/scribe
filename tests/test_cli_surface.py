"""Tests for the CLI-surface detector (`extraction/cli_surface.py`).

This module exists specifically because a real end-to-end run (a local Ollama model
documenting an unrelated repo) fabricated a plausible-looking but entirely wrong CLI
reference -- the extracted `GraphContext` never captured CLI subcommands/flags in the
first place, so the model had nothing real to ground against and invented one.
"""

from __future__ import annotations

from scribe.extraction.cli_surface import (
    build_cli_surface_text,
    detect_cli_surface,
    render_cli_surface_text,
)


def _write(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def test_detect_cli_surface_finds_argparse_subcommands_and_flags(tmp_path):
    _write(
        tmp_path / "pkg" / "cli.py",
        """
import argparse

def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    create = sub.add_parser("create")
    create.add_argument("--config")
    create.add_argument("--issues")
    discover = sub.add_parser("discover")
    discover.add_argument("--fields")
""",
    )

    surfaces = detect_cli_surface(tmp_path)

    assert len(surfaces) == 1
    surface = surfaces[0]
    assert surface.source_file == "pkg/cli.py"
    assert surface.subcommands == ["create", "discover"]
    assert surface.flags == ["--config", "--fields", "--issues"]


def test_detect_cli_surface_finds_click_commands_and_options(tmp_path):
    _write(
        tmp_path / "cli.py",
        """
import click

@click.group()
def cli():
    pass

@cli.command("generate")
@click.option("--repo")
@click.option("--mode")
def generate(repo, mode):
    pass
""",
    )

    surfaces = detect_cli_surface(tmp_path)

    assert len(surfaces) == 1
    assert surfaces[0].subcommands == ["generate"]
    assert surfaces[0].flags == ["--mode", "--repo"]


def test_detect_cli_surface_returns_empty_when_nothing_found(tmp_path):
    _write(tmp_path / "cli.py", "def main():\n    print('hello')\n")
    assert detect_cli_surface(tmp_path) == []


def test_detect_cli_surface_ignores_non_entry_point_files(tmp_path):
    _write(
        tmp_path / "utils.py",
        'import argparse\nparser = argparse.ArgumentParser()\nparser.add_argument("--ignored")\n',
    )
    assert detect_cli_surface(tmp_path) == []


def test_render_cli_surface_text_reports_no_detection_explicitly():
    text = render_cli_surface_text([])
    assert "No CLI subcommands/flags were reliably detected" in text
    assert "Do NOT invent" in text


def test_render_cli_surface_text_includes_detected_facts(tmp_path):
    _write(
        tmp_path / "cli.py",
        'import argparse\np = argparse.ArgumentParser()\nsub = p.add_subparsers()\nsub.add_parser("run")\n',
    )
    text = build_cli_surface_text(tmp_path)
    assert "cli.py" in text
    assert "run" in text
    assert "these are the" in text.lower()
