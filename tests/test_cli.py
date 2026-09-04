"""CLI-level tests for cross-repo usability fixes.

Uses Click's CliRunner so these exercise the actual command surface (option
parsing, defaults, error messages) rather than the underlying functions
directly.
"""

from __future__ import annotations

from click.testing import CliRunner

from scribe.cli import cli
from scribe.providers.registry import PROVIDER_PRESETS


def test_dry_run_accepts_an_unlisted_provider_paired_with_base_url(tmp_path, monkeypatch):
    """Regression test: --provider used to be a click.Choice restricted to the
    built-in registry, which rejected the documented --base-url escape hatch
    for unlisted OpenAI-compatible providers before the command even ran."""
    monkeypatch.delenv("SCRIBE_API_KEY", raising=False)
    runner = CliRunner()
    result = runner.invoke(
        cli,
        [
            "generate",
            "--repo",
            str(tmp_path),
            "--provider",
            "some-unlisted-vendor",
            "--base-url",
            "https://example.internal/v1",
            "--dry-run",
        ],
    )
    assert result.exit_code == 0, result.output
    assert "Invalid value" not in result.output


def test_output_defaults_relative_to_repo_not_cwd(tmp_path, monkeypatch):
    """Regression test: --output used to default to `./docs` relative to the
    CWD, not --repo, which silently wrote docs in the wrong place when the
    tool was pointed at a repo other than the current directory."""
    monkeypatch.chdir(tmp_path)  # CWD is deliberately NOT the target repo
    other_repo = tmp_path / "some_other_repo"
    other_repo.mkdir()

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--repo", str(other_repo), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert (other_repo / "docs" / "_dry_run_prompt.md").exists()
    assert not (tmp_path / "docs").exists()


def test_no_credentials_and_no_ollama_prints_setup_guidance_and_exits_nonzero(tmp_path, monkeypatch):
    monkeypatch.delenv("SCRIBE_API_KEY", raising=False)
    for preset in PROVIDER_PRESETS.values():
        monkeypatch.delenv(preset.api_key_env_var, raising=False)

    def _raise(*_args, **_kwargs):
        raise OSError("no local server")

    # Patch the actual network call `is_ollama_running` makes, not the function
    # object itself -- its default `ollama_probe` argument is bound at def time,
    # so patching the module-level name wouldn't affect an already-bound default.
    monkeypatch.setattr("urllib.request.urlopen", _raise)

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--repo", str(tmp_path)])

    assert result.exit_code == 1
    assert "FREE" in result.output
    assert "PAID" in result.output


def test_check_exits_nonzero_when_never_generated(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--repo", str(tmp_path), "--check"])
    assert result.exit_code == 1
    assert "Stale" in result.output


def test_init_writes_scribe_toml_and_generate_picks_up_its_mode(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # CWD deliberately NOT the target repo, matching real usage
    other_repo = tmp_path / "some_other_repo"
    other_repo.mkdir()

    runner = CliRunner()
    init_result = runner.invoke(cli, ["init", "--repo", str(other_repo)], input="operator_split\n\ndocs\n")
    assert init_result.exit_code == 0, init_result.output
    assert (other_repo / "scribe.toml").exists()

    generate_result = runner.invoke(cli, ["generate", "--repo", str(other_repo), "--dry-run"])
    assert generate_result.exit_code == 0, generate_result.output
    assert "operator_split" in generate_result.output


def test_relative_output_dir_from_config_file_resolves_against_repo_not_cwd(tmp_path, monkeypatch):
    """Regression test: a relative output_dir from scribe.toml used to resolve
    against the CWD (like --output once did), silently writing outside --repo."""
    monkeypatch.chdir(tmp_path)
    other_repo = tmp_path / "some_other_repo"
    other_repo.mkdir()
    (other_repo / "scribe.toml").write_text('output_dir = "generated"\n', encoding="utf-8")

    runner = CliRunner()
    result = runner.invoke(cli, ["generate", "--repo", str(other_repo), "--dry-run"])

    assert result.exit_code == 0, result.output
    assert (other_repo / "generated" / "_dry_run_prompt.md").exists()
    assert not (tmp_path / "generated").exists()


def test_org_context_command_scaffolds_template(tmp_path):
    runner = CliRunner()
    result = runner.invoke(cli, ["org-context", "--repo", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert (tmp_path / "scribe.org.toml").exists()
    assert "[org_context]" in (tmp_path / "scribe.org.toml").read_text(encoding="utf-8")


def test_org_context_command_does_not_overwrite_existing_file(tmp_path):
    (tmp_path / "scribe.org.toml").write_text("# hand-edited\n", encoding="utf-8")
    runner = CliRunner()
    result = runner.invoke(cli, ["org-context", "--repo", str(tmp_path)])

    assert result.exit_code == 0, result.output
    assert "hand-edited" in (tmp_path / "scribe.org.toml").read_text(encoding="utf-8")
    assert "already exists" in result.output
