"""S.C.R.I.B.E. CLI entry point.

Usage:
    scribe generate --mode operator_split --repo /path/to/project
    scribe models
"""

from __future__ import annotations

import dataclasses
import os
import shutil
import subprocess
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from scribe import pipeline
from scribe.config import (
    DEFAULT_MAX_REPAIR_ATTEMPTS,
    DEFAULT_TOKEN_BUDGET,
    ScribeConfig,
)
from scribe.constants import AudienceMode
from scribe.extraction.cache import DEFAULT_CACHE_ROOT
from scribe.extraction.extractor import (
    GraphifyyContractError,
    GraphifyyMissingAction,
    GraphifyyNotFoundError,
)
from scribe.generation.doc_plan import DocPlan, DocPlanContractError
from scribe.generation.writer import DocumentCountMismatchError
from scribe.pipeline import (
    CostConfirmationRequiredError,
    GenerationFailedError,
    NoExistingPlanError,
    OverwriteConfirmationRequiredError,
    TokenEstimateConfirmationRequiredError,
)
from scribe.project.config_loader import CONFIG_FIELDS, load_project_config
from scribe.project.notes import NOTES_FILENAME, notes_path
from scribe.project.org_context import ORG_CONTEXT_FILENAME, org_context_path, write_org_context_template
from scribe.project.presets import (
    PRESET_FIELDS,
    PresetError,
    delete_preset,
    load_preset,
    load_presets,
    presets_path,
    save_preset,
)
from scribe.providers.llm_client import UnsupportedProviderError
from scribe.providers.registry import NATIVE_PROVIDERS, PROVIDER_PRESETS
from scribe.providers.resolution import (
    NoProviderResolvedError,
    resolve_provider_and_key,
)

console = Console()

KNOWN_PROVIDERS = sorted(NATIVE_PROVIDERS | set(PROVIDER_PRESETS))


@click.group()
@click.version_option(package_name="scribe")
def cli() -> None:
    """S.C.R.I.B.E. - System Context & Repository Intelligence Bridge Engine.

    Generates multi-tiered, audience-aware documentation suites from a
    Graphifyy-derived knowledge graph of your codebase (or, if Graphifyy
    isn't installed, a built-in native fallback extractor).
    """


@cli.command()
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Path to the repository root to document.",
)
@click.option(
    "--mode",
    type=click.Choice([m.value for m in AudienceMode]),
    default=AudienceMode.LEAN_TECHNICAL.value,
    show_default=True,
    help="Target audience/output structure.",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory to write the generated documentation suite into. Defaults to <repo>/docs.",
)
@click.option(
    "--provider",
    default=None,
    help=(
        "LLM provider. If omitted, S.C.R.I.B.E. detects it from --api-key's format, an env var "
        "like ANTHROPIC_API_KEY, or a locally running Ollama server, in that order. Known: "
        f"{', '.join(KNOWN_PROVIDERS)}. Any other OpenAI-compatible provider works too, paired "
        "with --base-url."
    ),
)
@click.option(
    "--model",
    default=None,
    help="Model identifier to send to the provider's API. Defaults to that provider's top recommendation.",
)
@click.option(
    "--api-key",
    envvar="SCRIBE_API_KEY",
    default=None,
    help="API key for the selected provider. Falls back to SCRIBE_API_KEY env var.",
)
@click.option(
    "--base-url",
    default=None,
    help="Override the provider's API base URL (for unlisted OpenAI-compatible endpoints).",
)
@click.option(
    "--no-cache",
    is_flag=True,
    default=False,
    help="Skip the extraction cache entirely: don't read OR write it this run.",
)
@click.option(
    "--refresh-cache",
    is_flag=True,
    default=False,
    help="Force a fresh extraction (skip reading the cache) but still write the result for next time.",
)
@click.option(
    "--force-native-extractor",
    is_flag=True,
    default=False,
    help="Skip Graphifyy even if it's on PATH and use the built-in native extractor.",
)
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=(
        f"Where to store the extraction cache. Defaults to a user-level directory "
        f"({DEFAULT_CACHE_ROOT}), never inside --repo."
    ),
)
@click.option(
    "--max-repair-attempts",
    type=int,
    default=DEFAULT_MAX_REPAIR_ATTEMPTS,
    show_default=True,
    help="How many times to re-prompt the LLM if its output fails validation.",
)
@click.option(
    "--token-budget",
    type=int,
    default=DEFAULT_TOKEN_BUDGET,
    show_default=True,
    help="Approximate token budget for the graph digest injected into the prompt.",
)
@click.option(
    "--chunked",
    is_flag=True,
    default=False,
    help="Force chunked map-reduce generation (one call per top-level package) even for small repos.",
)
@click.option(
    "--yes",
    "-y",
    "assume_yes",
    is_flag=True,
    default=False,
    help="Skip the confirmation prompt before a run estimated to exceed --token-budget.",
)
@click.option(
    "--temperature",
    type=float,
    default=None,
    help="Sampling temperature passed to the provider, if it supports one.",
)
@click.option(
    "--max-tokens",
    type=int,
    default=None,
    help="Max output tokens passed to the provider. Defaults to the provider's own default.",
)
@click.option(
    "--incremental/--no-incremental",
    default=True,
    help=(
        "Skip regeneration if the repo hasn't changed since the last run "
        "(tracked via a manifest in --output)."
    ),
)
@click.option(
    "--check",
    is_flag=True,
    default=False,
    help=(
        "Drift-check only: no extraction, no LLM call. Exits non-zero if docs are "
        "stale relative to code. Safe for CI."
    ),
)
@click.option(
    "--doc-plan-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=None,
    help=(
        "Path to a JSON documentation-structure plan to use instead of (or compare against) "
        "the structure derived from this repo. See the generated .scribe_plan.json for the shape."
    ),
)
@click.option(
    "--refresh-plan",
    is_flag=True,
    default=False,
    help="Re-derive the documentation structure via the LLM even if it's cached for this repo.",
)
@click.option(
    "--preset",
    "preset_name",
    default=None,
    help=(
        "Name of a preset from this repo's scribe.presets.json to apply. Precedence: explicit "
        "flags on this command line > --preset values > scribe.toml values > built-in default."
    ),
)
@click.option(
    "--verbose",
    is_flag=True,
    default=False,
    help="Print every pipeline status message on its own line instead of a single updating status line.",
)
@click.option(
    "--quiet",
    is_flag=True,
    default=False,
    help="Suppress status messages; print only the final result or an error.",
)
@click.option(
    "--dry-run",
    is_flag=True,
    default=False,
    help="Assemble the prompt and write it to disk without calling the LLM.",
)
@click.pass_context
def generate(
    ctx: click.Context,
    repo_path: Path,
    mode: str,
    output_dir: Path | None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    no_cache: bool,
    refresh_cache: bool,
    force_native_extractor: bool,
    cache_dir: Path | None,
    max_repair_attempts: int,
    token_budget: int,
    chunked: bool,
    assume_yes: bool,
    temperature: float | None,
    max_tokens: int | None,
    incremental: bool,
    check: bool,
    doc_plan_file: Path | None,
    refresh_plan: bool,
    preset_name: str | None,
    verbose: bool,
    quiet: bool,
    dry_run: bool,
) -> None:
    """Generate a documentation suite for REPO using the selected MODE."""
    resolved_repo_path = repo_path.resolve()

    # Project-level defaults (scribe.toml / [tool.scribe]) fill in anything left at its CLI
    # default; an explicitly-passed flag always wins. See project/config_loader.py. A named
    # --preset (scribe.presets.json) is more specific than scribe.toml's blanket defaults, so
    # it wins when both apply to the same field -- see project/presets.py.
    project_defaults = load_project_config(resolved_repo_path)
    preset_values = {}
    if preset_name is not None:
        preset_values = load_preset(resolved_repo_path, preset_name) or {}
        if not preset_values:
            console.print(
                f"[bold yellow]No preset named '{preset_name}' found in "
                f"{presets_path(resolved_repo_path).name}.[/]"
            )
    merged_defaults = {**project_defaults, **preset_values}
    local_values = {name: value for name, value in locals().items() if name in CONFIG_FIELDS}
    for name in CONFIG_FIELDS:
        if name in merged_defaults and ctx.get_parameter_source(name) == click.ParameterSource.DEFAULT:
            local_values[name] = merged_defaults[name]
    mode, provider, model, output_dir, max_repair_attempts, token_budget, chunked = (
        local_values["mode"],
        local_values["provider"],
        local_values["model"],
        local_values["output_dir"],
        local_values["max_repair_attempts"],
        local_values["token_budget"],
        local_values["chunked"],
    )
    # Preset-only knobs not covered by CONFIG_FIELDS/scribe.toml today.
    if (
        "max_tokens" in preset_values
        and ctx.get_parameter_source("max_tokens") == click.ParameterSource.DEFAULT
    ):
        max_tokens = preset_values["max_tokens"]
    if (
        "temperature" in preset_values
        and ctx.get_parameter_source("temperature") == click.ParameterSource.DEFAULT
    ):
        temperature = preset_values["temperature"]
    preset_api_key_env = preset_values.get("api_key_env")
    if (
        preset_api_key_env
        and api_key is None
        and ctx.get_parameter_source("api_key") == click.ParameterSource.DEFAULT
    ):
        api_key = os.environ.get(preset_api_key_env)
    if isinstance(output_dir, str):
        output_dir = Path(output_dir)

    # A relative --output (whether from the CLI or scribe.toml) is relative to --repo,
    # never to the current working directory -- this tool is meant to be pointed at
    # repos other than the one you happen to be sitting in.
    if output_dir is None:
        resolved_output_dir = resolved_repo_path / "docs"
    elif output_dir.is_absolute():
        resolved_output_dir = output_dir
    else:
        resolved_output_dir = resolved_repo_path / output_dir
    resolved_output_dir = resolved_output_dir.resolve()

    if check:
        check_config = ScribeConfig(
            repo_path=resolved_repo_path,
            output_dir=resolved_output_dir,
            mode=AudienceMode(mode),
            provider="unresolved",
            model="unresolved",
            api_key=None,
            cache_dir=cache_dir or DEFAULT_CACHE_ROOT,
        )
        report = pipeline.check_drift(check_config, on_status=console.print)
        if report.up_to_date:
            console.print(f"[bold green]Up to date:[/] {report.reason}")
            raise SystemExit(0)
        console.print(f"[bold red]Stale:[/] {report.reason}")
        raise SystemExit(1)

    console.print(f"[bold cyan]S.C.R.I.B.E.[/] generating '{mode}' suite for [bold]{resolved_repo_path}[/]")

    if dry_run:
        resolved_provider, resolved_api_key = provider or "unresolved", None
    else:
        try:
            resolution = resolve_provider_and_key(provider, api_key)
        except NoProviderResolvedError as exc:
            console.print(f"[bold yellow]{exc}[/]")
            raise SystemExit(1) from exc
        if resolution.note:
            console.print(f"[dim]{resolution.note}[/]")
        resolved_provider, resolved_api_key = resolution.provider, resolution.api_key

    resolved_model = model or (_default_model_for(resolved_provider) if not dry_run else "unresolved")
    config = ScribeConfig(
        repo_path=resolved_repo_path,
        output_dir=resolved_output_dir,
        mode=AudienceMode(mode),
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        base_url=base_url,
        dry_run=dry_run,
        use_cache=not no_cache,
        refresh_cache=refresh_cache,
        force_native_extractor=force_native_extractor,
        max_repair_attempts=max_repair_attempts,
        token_budget=token_budget,
        cache_dir=cache_dir or DEFAULT_CACHE_ROOT,
        chunked=chunked,
        assume_yes=assume_yes,
        temperature=temperature,
        max_tokens=max_tokens,
        incremental=incremental,
        doc_plan_file=doc_plan_file,
        refresh_plan=refresh_plan,
    )

    try:
        written = _run_with_confirmations(config, verbose=verbose, quiet=quiet)
    except (
        GraphifyyNotFoundError,
        GraphifyyContractError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        console.print(f"[bold red]Extraction failed:[/] {exc}")
        raise SystemExit(1) from exc
    except (UnsupportedProviderError, ValueError) as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        raise SystemExit(1) from exc
    except (DocumentCountMismatchError, GenerationFailedError, DocPlanContractError) as exc:
        console.print(f"[bold red]Generation failed:[/] {exc}")
        raise SystemExit(1) from exc

    console.print(f"[bold green]Done.[/] Wrote {len(written)} file(s) to [bold]{config.output_dir}[/]:")
    for path in written:
        console.print(f"  - {path.name}")


@cli.command("revise-plan")
@click.argument("request", required=False, default="")
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Path to the repository root whose documentation structure should be revised.",
)
@click.option(
    "--mode",
    type=click.Choice([m.value for m in AudienceMode]),
    default=AudienceMode.LEAN_TECHNICAL.value,
    show_default=True,
    help="Must match the mode the existing plan was generated for.",
)
@click.option(
    "--output",
    "output_dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Directory containing the existing .scribe_plan.json. Defaults to <repo>/docs.",
)
@click.option("--provider", default=None, help="LLM provider (see `scribe generate --help`).")
@click.option(
    "--model", default=None, help="Model identifier. Defaults to the provider's top recommendation."
)
@click.option("--api-key", envvar="SCRIBE_API_KEY", default=None, help="API key for the selected provider.")
@click.option("--base-url", default=None, help="Override the provider's API base URL.")
@click.option(
    "--cache-dir",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help=f"Where the extraction cache lives. Defaults to {DEFAULT_CACHE_ROOT}.",
)
@click.option("--verbose", is_flag=True, default=False, help="Print every pipeline status message.")
@click.option("--quiet", is_flag=True, default=False, help="Suppress status messages.")
def revise_plan(
    request: str,
    repo_path: Path,
    mode: str,
    output_dir: Path | None,
    provider: str | None,
    model: str | None,
    api_key: str | None,
    base_url: str | None,
    cache_dir: Path | None,
    verbose: bool,
    quiet: bool,
) -> None:
    """Revise REPO's existing documentation structure per REQUEST (a freeform description of the change).

    Requires `scribe generate` to have already run at least once (needs an existing
    .scribe_plan.json to revise). Also honors any standing notes in scribe.notes.md, if present.
    Only updates the STRUCTURE (.scribe_plan.json and scribe-doc-suite-justification.md) -- run
    `scribe generate` afterward to apply it to actual page content.
    """
    resolved_repo_path = repo_path.resolve()
    if output_dir is None:
        resolved_output_dir = resolved_repo_path / "docs"
    elif output_dir.is_absolute():
        resolved_output_dir = output_dir
    else:
        resolved_output_dir = resolved_repo_path / output_dir
    resolved_output_dir = resolved_output_dir.resolve()

    if not request and not notes_path(resolved_repo_path).exists():
        console.print(
            f"[bold yellow]Nothing to revise:[/] pass REQUEST, or write {NOTES_FILENAME} in the repo first."
        )
        raise SystemExit(1)

    try:
        resolution = resolve_provider_and_key(provider, api_key)
    except NoProviderResolvedError as exc:
        console.print(f"[bold yellow]{exc}[/]")
        raise SystemExit(1) from exc
    if resolution.note:
        console.print(f"[dim]{resolution.note}[/]")
    resolved_provider, resolved_api_key = resolution.provider, resolution.api_key
    resolved_model = model or _default_model_for(resolved_provider)

    config = ScribeConfig(
        repo_path=resolved_repo_path,
        output_dir=resolved_output_dir,
        mode=AudienceMode(mode),
        provider=resolved_provider,
        model=resolved_model,
        api_key=resolved_api_key,
        base_url=base_url,
        cache_dir=cache_dir or DEFAULT_CACHE_ROOT,
    )

    try:
        with console.status("[bold cyan]Revising documentation structure...", spinner="dots") as status_line:
            reporter = _make_status_reporter(status_line, verbose=verbose, quiet=quiet)
            revised = pipeline.revise_doc_plan(config, request, on_status=reporter)
    except (
        GraphifyyNotFoundError,
        GraphifyyContractError,
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
    ) as exc:
        console.print(f"[bold red]Extraction failed:[/] {exc}")
        raise SystemExit(1) from exc
    except (UnsupportedProviderError, ValueError) as exc:
        console.print(f"[bold red]Configuration error:[/] {exc}")
        raise SystemExit(1) from exc
    except NoExistingPlanError as exc:
        console.print(f"[bold yellow]{exc}[/]")
        raise SystemExit(1) from exc
    except DocPlanContractError as exc:
        console.print(f"[bold red]Revision failed:[/] {exc}")
        raise SystemExit(1) from exc

    console.print(f"[bold green]Revised plan[/] ({len(revised.doc_ids)} doc(s)):")
    for doc_id in revised.doc_ids:
        console.print(f"  - {doc_id}")
    console.print(f"Updated [bold]{config.output_dir / '.scribe_plan.json'}[/] and the justification doc.")
    console.print("Run [bold]scribe generate[/] to apply this structure to page content.")


def _make_status_reporter(status_line, *, verbose: bool, quiet: bool):
    """Return an `on_status` callback matching the requested verbosity.

    Default: overwrite a single live status line (current behavior).
    `--verbose`: print every message as its own line, keeping full history visible.
    `--quiet`: suppress status messages entirely; errors/the final summary still print.
    """
    if quiet:
        return lambda _msg: None
    if verbose:
        return lambda msg: console.print(f"[dim]{msg}[/]")
    return lambda msg: status_line.update(f"[bold cyan]{msg}")


def _confirm_graphifyy_missing() -> GraphifyyMissingAction:
    console.print("[yellow]Graphifyy isn't installed.[/]")
    if click.confirm("Install it now (pip install graphifyy) and retry extraction?", default=True):
        return GraphifyyMissingAction.INSTALL_AND_RETRY
    return GraphifyyMissingAction.USE_FALLBACK


def _confirm_graphifyy_failed(detail: str, manual_command: str) -> bool:
    console.print(f"[bold yellow]Graphifyy run failed:[/] {detail}")
    console.print(f"You can investigate/run it yourself:\n  [bold]{manual_command}[/]")
    return click.confirm("Continue this run with the native fallback extractor?", default=True)


def _confirm_doc_plan_conflict(recommended: DocPlan, user_plan: DocPlan) -> DocPlan:
    console.print("[yellow]Your --doc-plan-file differs from the structure derived from this repo:[/]")
    console.print(f"  Recommended ({len(recommended.doc_ids)} doc(s)): {', '.join(recommended.doc_ids)}")
    console.print(f"  Yours ({len(user_plan.doc_ids)} doc(s)): {', '.join(user_plan.doc_ids)}")
    if recommended.rationale:
        console.print(f"  [dim]Why the recommended structure: {recommended.rationale}[/]")
    if click.confirm("Use the recommended (repo-derived) structure instead of your file?", default=False):
        return recommended
    return user_plan


def _run_with_confirmations(
    config: ScribeConfig, *, verbose: bool = False, quiet: bool = False
) -> list[Path]:
    """Run the pipeline, prompting for confirmation once if cost or overwrite checks require it.

    Also prompts (interactively, unless `--quiet`/`--yes` or stdin isn't a TTY) when Graphifyy
    is missing (offering to install it and retry) or when an installed Graphifyy actually fails
    to run (offering the manual command, then asking whether to continue with the fallback).
    """
    interactive = not quiet and not config.assume_yes and sys.stdin.isatty()

    def _attempt(run_config: ScribeConfig) -> list[Path]:
        with console.status("[bold cyan]Running pipeline...", spinner="dots") as status_line:
            reporter = _make_status_reporter(status_line, verbose=verbose, quiet=quiet)
            return pipeline.run(
                run_config,
                on_status=reporter,
                on_graphifyy_missing=_confirm_graphifyy_missing if interactive else None,
                on_graphifyy_failed=_confirm_graphifyy_failed if interactive else None,
                on_doc_plan_conflict=_confirm_doc_plan_conflict if interactive else None,
            )

    try:
        return _attempt(config)
    except TokenEstimateConfirmationRequiredError as exc:
        console.print(
            f"[bold cyan]About to generate {len(exc.page_token_estimates)} page(s) "
            f"(~{exc.total_estimated_tokens:,} total estimated prompt tokens):[/]"
        )
        table = Table(show_header=True, header_style="bold")
        table.add_column("Page")
        table.add_column("Est. prompt tokens", justify="right")
        for doc_id, tokens in sorted(exc.page_token_estimates.items(), key=lambda kv: -kv[1]):
            table.add_row(doc_id, f"{tokens:,}")
        console.print(table)
        if not click.confirm("Proceed with generation?", default=True):
            raise SystemExit(1) from exc
        return _attempt(dataclasses.replace(config, assume_yes=True))
    except (CostConfirmationRequiredError, OverwriteConfirmationRequiredError) as exc:
        console.print(f"[bold yellow]{exc}[/]")
        prompt = "Overwrite?" if isinstance(exc, OverwriteConfirmationRequiredError) else "Proceed anyway?"
        if not click.confirm(prompt, default=False):
            raise SystemExit(1) from exc
        return _attempt(dataclasses.replace(config, assume_yes=True))


@cli.command()
def models() -> None:
    """List supported providers and their recommended models."""
    table = Table(title="S.C.R.I.B.E. Supported Providers")
    table.add_column("Provider")
    table.add_column("Cost")
    table.add_column("Recommended Models")
    table.add_column("Notes")

    for preset in PROVIDER_PRESETS.values():
        table.add_row(preset.name, preset.cost, ", ".join(preset.recommended_models), preset.notes)

    console.print(table)
    console.print("\nSee [bold]MODELS.md[/] for the full, versioned recommendation list.")


def _default_model_for(provider: str) -> str:
    preset = PROVIDER_PRESETS.get(provider)
    if preset and preset.recommended_models:
        return preset.recommended_models[0]
    raise UnsupportedProviderError(
        f"No default model known for provider {provider!r}; pass --model explicitly."
    )


@cli.group("presets")
def presets_group() -> None:
    """Manage named per-repo presets (scribe.presets.json) usable via `generate --preset NAME`."""


def _presets_repo_option():
    return click.option(
        "--repo",
        "repo_path",
        type=click.Path(exists=True, file_okay=False, path_type=Path),
        default=Path("."),
        show_default=True,
        help="Repo whose scribe.presets.json to use.",
    )


@presets_group.command("list")
@_presets_repo_option()
def presets_list(repo_path: Path) -> None:
    """List every named preset defined for REPO."""
    resolved_repo_path = repo_path.resolve()
    presets = load_presets(resolved_repo_path)
    if not presets:
        console.print(f"No presets found in {presets_path(resolved_repo_path)}.")
        return
    table = Table(title=f"Presets in {presets_path(resolved_repo_path).name}")
    table.add_column("Name")
    table.add_column("Fields")
    for name, fields in presets.items():
        table.add_row(name, ", ".join(f"{k}={v}" for k, v in fields.items()))
    console.print(table)


@presets_group.command("show")
@click.argument("name")
@_presets_repo_option()
def presets_show(name: str, repo_path: Path) -> None:
    """Print one named preset's fields."""
    resolved_repo_path = repo_path.resolve()
    preset = load_preset(resolved_repo_path, name)
    if preset is None:
        console.print(
            f"[bold yellow]No preset named '{name}' found in {presets_path(resolved_repo_path).name}.[/]"
        )
        raise SystemExit(1)
    for key, value in preset.items():
        console.print(f"{key}: {value}")


@presets_group.command("save")
@click.argument("name")
@click.option(
    "--set",
    "set_values",
    multiple=True,
    metavar="KEY=VALUE",
    help=f"Preset field to set, repeatable. Valid keys: {', '.join(PRESET_FIELDS)}.",
)
@_presets_repo_option()
def presets_save(name: str, set_values: tuple[str, ...], repo_path: Path) -> None:
    """Save/overwrite a named preset, e.g. `--set mode=lean_technical --set provider=ollama`."""
    resolved_repo_path = repo_path.resolve()
    values: dict[str, str] = {}
    for item in set_values:
        if "=" not in item:
            raise click.BadParameter(f"--set must be KEY=VALUE, got {item!r}")
        key, _, value = item.partition("=")
        if key not in PRESET_FIELDS:
            raise click.BadParameter(f"Unknown preset field {key!r}. Valid: {', '.join(PRESET_FIELDS)}")
        values[key] = value
    try:
        written = save_preset(resolved_repo_path, name, values)
    except PresetError as exc:
        console.print(f"[bold red]{exc}[/]")
        raise SystemExit(1) from exc
    console.print(f"[bold green]Saved[/] preset '{name}' to {written}.")


@presets_group.command("delete")
@click.argument("name")
@_presets_repo_option()
def presets_delete(name: str, repo_path: Path) -> None:
    """Delete one named preset."""
    resolved_repo_path = repo_path.resolve()
    if delete_preset(resolved_repo_path, name):
        console.print(f"[bold green]Deleted[/] preset '{name}'.")
    else:
        console.print(f"No preset named '{name}' found -- nothing to delete.")


@cli.command()
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Repo to generate documentation for via the GUI.",
)
@click.option(
    "--port",
    type=int,
    default=0,
    show_default=False,
    help="Port to bind the local GUI server to. Defaults to an OS-assigned free port.",
)
@click.option(
    "--no-browser",
    is_flag=True,
    default=False,
    help="Don't automatically open the default browser -- just print the URL.",
)
def gui(repo_path: Path, port: int, no_browser: bool) -> None:
    """Launch a local browser-based GUI for REPO -- zero extra dependencies (stdlib only).

    Bound to 127.0.0.1 only; never reachable over the network. Ctrl+C stops the server.
    """
    from scribe.gui.server import run_gui

    run_gui(repo_path.resolve(), port=port, open_browser=not no_browser)


@cli.command()
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Repo to generate documentation for via the TUI.",
)
def tui(repo_path: Path) -> None:
    """Launch a terminal UI for REPO -- same form/preset/log flow as `scribe gui`.

    Requires the optional `tui` extra (`pip install scribe[tui]`); the browser GUI
    (`scribe gui`) needs no extra install at all.
    """
    try:
        from scribe.gui.tui import run_tui
    except ImportError as exc:
        console.print(
            "[bold yellow]The TUI needs the optional 'tui' extra, which isn't installed.[/]\n"
            "Install it with:\n"
            "  pip install scribe[tui]\n"
            "Or use the zero-dependency browser GUI instead: scribe gui"
        )
        raise SystemExit(1) from exc

    run_tui(repo_path.resolve())


@cli.command("org-context")
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Repo to scaffold/inspect the organizational-context file for.",
)
def org_context_cmd(repo_path: Path) -> None:
    """Scaffold or report on `scribe.org.toml` -- the ONLY source of org/infra facts.

    Scribe never invents a company name, contact, account id, or environment name -- it
    either cites what's in this file or says the information wasn't provided. Never
    overwrites an existing file.
    """
    resolved_repo_path = repo_path.resolve()
    path = org_context_path(resolved_repo_path)
    if path.exists():
        console.print(f"[bold]{ORG_CONTEXT_FILENAME}[/] already exists at [bold]{path}[/]; not overwriting.")
        return
    written_path = write_org_context_template(resolved_repo_path)
    console.print(f"[bold green]Wrote[/] {written_path}")
    console.print("Fill in whatever fields apply, leave the rest blank -- scribe will never invent them.")


@cli.command()
@click.option(
    "--repo",
    "repo_path",
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    default=Path("."),
    show_default=True,
    help="Repo to write scribe.toml into.",
)
def init(repo_path: Path) -> None:
    """Interactive first-run setup: writes `scribe.toml` with your project defaults."""
    resolved_repo_path = repo_path.resolve()
    console.print(f"[bold cyan]S.C.R.I.B.E. init[/] for [bold]{resolved_repo_path}[/]")

    mode = click.prompt(
        "Mode", type=click.Choice([m.value for m in AudienceMode]), default=AudienceMode.LEAN_TECHNICAL.value
    )
    provider = click.prompt(
        "Default provider (blank = auto-detect from --api-key/env var/Ollama each run)",
        default="",
        show_default=False,
    )
    output_dir = click.prompt("Output directory", default="docs")

    if shutil.which("graphify"):
        console.print("[green]Graphifyy ('graphify') found on PATH -- will be used for extraction.[/]")
    else:
        console.print(
            "[yellow]Graphifyy not found on PATH -- will use the built-in native fallback extractor.[/]"
        )

    if provider:
        preset = PROVIDER_PRESETS.get(provider)
        if preset and preset.requires_api_key:
            if os.environ.get(preset.api_key_env_var):
                console.print(f"[green]{preset.api_key_env_var} is already set in your environment.[/]")
            else:
                console.print(
                    f"[yellow]{preset.api_key_env_var} is not set -- set it "
                    "before running `scribe generate`.[/]"
                )

    lines = [f'mode = "{mode}"', f'output_dir = "{output_dir}"']
    if provider:
        lines.append(f'provider = "{provider}"')
    config_path = resolved_repo_path / "scribe.toml"
    config_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    console.print(f"[bold green]Wrote {config_path}.[/] Run `scribe generate` to get started.")


if __name__ == "__main__":
    cli()
