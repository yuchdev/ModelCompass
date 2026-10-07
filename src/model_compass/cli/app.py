"""Scriptable command-line interface for model-compass."""

from __future__ import annotations

import asyncio
import importlib
import json
import os
import platform
import sqlite3
import sys
import traceback
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from enum import Enum, IntEnum, StrEnum
from pathlib import Path
from typing import Annotated, Any, NoReturn, Optional

import typer
from pydantic import BaseModel
from rich.console import Console
from rich.table import Table

from model_compass import __version__
from model_compass.application import AnalyticsFacade, analytics
from model_compass.benchmarks import (
    BenchmarkRunConfig,
    RunnerBudget,
    evaluate_offline,
    load_dataset_jsonl,
    run_benchmark,
)
from model_compass.catalogs import CatalogService, LiteLLMCatalogAdapter, OpenRouterCatalogAdapter
from model_compass.config import AppPaths, default_paths
from model_compass.domain import BenchmarkResult, CatalogSnapshot, ModelProfile, RequestProfile
from model_compass.exceptions import ModelCompassError, NoEligibleModelError, StorageError
from model_compass.execution import CompletionRequest, LiteLLMBackend
from model_compass.metrics import FallbackTokenEstimator, summarize_observations
from model_compass.selection import (
    ObjectiveDirection,
    ParetoObjective,
    SelectionPolicy,
    check_eligibility,
    compare_models,
    estimate_request_cost,
    pareto_analysis,
)
from model_compass.storage import SQLiteObservationStore

app = typer.Typer(
    name="model-compass",
    help="Request-aware LLM model analytics, comparison, and selection.",
    no_args_is_help=True,
)
config_app = typer.Typer(no_args_is_help=True)
catalog_app = typer.Typer(no_args_is_help=True)
models_app = typer.Typer(invoke_without_command=True)
observations_app = typer.Typer(invoke_without_command=True)
benchmark_app = typer.Typer(no_args_is_help=True, invoke_without_command=True)
db_app = typer.Typer(no_args_is_help=True)
console = Console()
err_console = Console(stderr=True)


class OutputFormat(StrEnum):
    """Supported CLI output formats."""

    table = "table"
    json = "json"


class ExitCode(IntEnum):
    """Stable process exit-code categories."""

    SUCCESS = 0
    CLI_ERROR = 2
    NO_ELIGIBLE_MODEL = 3
    CATALOG_ERROR = 4
    EXECUTION_ERROR = 5
    STORAGE_ERROR = 6


@app.callback()
def _root(
    ctx: typer.Context,
    config: Annotated[Optional[Path], typer.Option("--config", help="Configuration file path")] = None,
    data_dir: Annotated[Optional[Path], typer.Option("--data-dir", help="Application data directory")] = None,
    cache_dir: Annotated[Optional[Path], typer.Option("--cache-dir", help="Catalog cache directory")] = None,
    db: Annotated[Optional[Path], typer.Option("--db", help="Observation database path")] = None,
    debug: Annotated[bool, typer.Option("--debug", help="Show tracebacks for command errors")] = False,
    no_color: Annotated[bool, typer.Option("--no-color", help="Disable colored output")] = False,
):
    """Configure paths and diagnostics for this invocation."""
    global console, err_console
    console = Console(no_color=no_color)
    err_console = Console(stderr=True, no_color=no_color)
    ctx.obj = {
        "config": config,
        "data_dir": data_dir,
        "cache_dir": cache_dir,
        "db": db,
        "debug": debug,
        "no_color": no_color,
        "analytics": None,
        "store": None,
    }


@app.command()
def version():
    """Print the installed package version."""
    print(__version__)


@app.command()
def doctor(
    ctx: typer.Context,
    output_format: Annotated[OutputFormat, typer.Option("--format", help="Output format: table or json")] = (
        OutputFormat.table
    ),
):
    """Report environment health and default paths."""
    paths = _effective_paths(ctx)
    try:
        importlib.import_module("litellm")
        litellm_ok = True
        litellm_error = None
    except ImportError as exc:
        litellm_ok = False
        litellm_error = str(exc)
    payload = {
        "schema_version": 1,
        "command": "doctor",
        "package_version": __version__,
        "python_version": sys.version,
        "platform": platform.platform(),
        "litellm_available": litellm_ok,
        "litellm_error": litellm_error,
        "paths": _path_data(paths),
        "database_path": str(_db_path(ctx)),
    }
    if output_format == OutputFormat.json:
        _print_json(payload)
        return
    table = Table(title="model-compass doctor")
    table.add_column("Check", style="bold")
    table.add_column("Value")
    table.add_row("Package version", __version__)
    table.add_row("Python version", sys.version.split()[0])
    table.add_row("Platform", platform.platform())
    table.add_row("LiteLLM available", "yes" if litellm_ok else f"no: {litellm_error}")
    for name, value in _path_data(paths).items():
        table.add_row(name.replace("_", " ").title(), value)
    table.add_row("Database", str(_db_path(ctx)))
    console.print(table)


@config_app.command("show")
def config_show(
    ctx: typer.Context,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Show the effective configuration paths and recognized environment keys."""
    paths = _effective_paths(ctx)
    options = ctx.obj
    payload = {
        "schema_version": 1,
        "command": "config show",
        "config_file": str(options["config"]) if options["config"] else None,
        "paths": _path_data(paths),
        "environment_keys": [
            key for key in ("OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY") if key in os.environ
        ],
    }
    if output_format == OutputFormat.json:
        _print_json(payload)
    else:
        table = Table(title="Configuration")
        table.add_column("Setting", style="bold")
        table.add_column("Value")
        for key, value in payload["paths"].items():
            table.add_row(key, value)
        table.add_row("Config file", payload["config_file"] or "not specified")
        table.add_row("Provider credentials", ", ".join(payload["environment_keys"]) or "none detected")
        console.print(table)


@config_app.command("paths")
def config_paths(
    ctx: typer.Context,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Print effective application paths without creating directories."""
    payload = {"schema_version": 1, "command": "config paths", "paths": _path_data(_effective_paths(ctx))}
    if output_format == OutputFormat.json:
        _print_json(payload)
    else:
        table = Table(title="Application paths")
        table.add_column("Path", style="bold")
        table.add_column("Value")
        for name, value in payload["paths"].items():
            table.add_row(name, value)
        console.print(table)


@catalog_app.command("refresh")
def catalog_refresh(
    ctx: typer.Context,
    source: Annotated[str, typer.Option(help="Catalog source: openrouter, litellm, or all")] = "all",
    force: Annotated[bool, typer.Option(help="Ignore fresh cached catalog data")] = False,
    offline: Annotated[bool, typer.Option(help="Require cached OpenRouter data")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Refresh catalog metadata and report source freshness and warnings."""
    try:
        snapshot, source_name = _refresh_catalog(ctx, source=source, force=force, offline=offline)
    except (ModelCompassError, ValueError) as exc:
        _fail(
            ctx,
            f"Unable to refresh catalog: {exc}",
            2 if isinstance(exc, ValueError) else 4,
            hint="Check connectivity or use --offline with a cached catalog.",
        )
    paths = _effective_paths(ctx)
    payload = {
        "schema_version": 1,
        "command": "catalog refresh",
        "source": source_name,
        "fetch_result": "stale-cache" if snapshot.stale else "success",
        "model_count": len(snapshot.models),
        "timestamp": snapshot.retrieved_at,
        "cache_path": str(paths.cache_dir / "catalog"),
        "cache_status": "stale" if snapshot.stale else "available",
        "warnings": list(snapshot.parse_warnings),
        "sources": [item.model_dump(mode="json") for item in snapshot.sources],
    }
    _emit(payload, output_format, _catalog_table(snapshot))


@catalog_app.command("sources")
def catalog_sources(
    ctx: typer.Context,
    offline: Annotated[bool, typer.Option(help="Use cached OpenRouter data only")] = True,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """List catalog sources present in a snapshot."""
    try:
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to read catalog sources: {exc}", 4)
    payload = {
        "schema_version": 1,
        "command": "catalog sources",
        "sources": [item.model_dump(mode="json") for item in snapshot.sources],
    }
    table = Table(title="Catalog sources")
    table.add_column("Source", style="bold")
    table.add_column("Retrieved")
    table.add_column("Stale")
    for item in snapshot.sources:
        table.add_row(item.name, _format_datetime(item.retrieved_at), str(item.stale).lower())
    _emit(payload, output_format, table)


@catalog_app.command("status")
def catalog_status(
    ctx: typer.Context,
    offline: Annotated[bool, typer.Option(help="Do not fetch a fresh catalog")] = True,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Show the current catalog snapshot status."""
    try:
        snapshot, source_name = _refresh_catalog(ctx, source="all", offline=offline)
    except ModelCompassError as exc:
        _fail(ctx, f"Catalog unavailable: {exc}", 4)
    payload = {
        "schema_version": 1,
        "command": "catalog status",
        "source": source_name,
        "model_count": len(snapshot.models),
        "retrieved_at": snapshot.retrieved_at,
        "stale": snapshot.stale,
        "cache_path": str(_effective_paths(ctx).cache_dir / "catalog"),
        "warnings": list(snapshot.parse_warnings),
    }
    table = Table(title="Catalog status")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Models", str(len(snapshot.models)))
    table.add_row("Retrieved", _format_datetime(snapshot.retrieved_at))
    table.add_row("Stale", str(snapshot.stale).lower())
    _emit(payload, output_format, table)


@models_app.callback()
def models_callback(
    ctx: typer.Context,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
):
    """List catalog models, or use ``models list`` and ``models show``."""
    if ctx.invoked_subcommand is None:
        _models_list(ctx, output_format=output_format, offline=offline)


@models_app.command("list")
def models_list(
    ctx: typer.Context,
    source: Annotated[Optional[str], typer.Option(help="Filter by catalog source")] = None,
    gateway: Annotated[Optional[str], typer.Option(help="Filter by gateway/provider substring")] = None,
    modality: Annotated[Optional[str], typer.Option(help="Required modality: text, vision, audio, or video")] = None,
    tools: Annotated[bool, typer.Option(help="Require tool calling")] = False,
    structured_output: Annotated[bool, typer.Option("--structured-output", help="Require structured output")] = False,
    reasoning: Annotated[bool, typer.Option(help="Require reasoning support")] = False,
    minimum_context: Annotated[Optional[int], typer.Option("--minimum-context", min=0)] = None,
    free_only: Annotated[
        bool, typer.Option("--free-only", help="Show models with known zero input and output prices")
    ] = False,
    search: Annotated[Optional[str], typer.Option(help="Substring in model name or ID")] = None,
    limit: Annotated[Optional[int], typer.Option(min=1)] = None,
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """List normalized models with capability, source, and price filters."""
    _models_list(
        ctx,
        source=source,
        gateway=gateway,
        modality=modality,
        tools=tools,
        structured_output=structured_output,
        reasoning=reasoning,
        minimum_context=minimum_context,
        free_only=free_only,
        search=search,
        limit=limit,
        offline=offline,
        output_format=output_format,
    )


@models_app.command("show")
def models_show(
    ctx: typer.Context,
    model: Annotated[str, typer.Argument(help="Canonical or provider-local model ID")],
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Show complete normalized details for one model."""
    try:
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
        profile = _find_profile(snapshot.models.values(), model)
        if profile is None:
            _fail(
                ctx, f"Model {model!r} was not found.", 2, hint="Run `model-compass models list` to see available IDs."
            )
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to load model: {exc}", 4)
    observation_summary = None
    summary_method = getattr(_analytics(ctx), "summarize_model", None)
    if summary_method is not None:
        try:
            observation_summary = summary_method(profile.identity.canonical_id, min_samples=1)
        except ModelCompassError as exc:
            _fail(ctx, f"Unable to read model observations: {exc}", 6)
    payload = {
        "schema_version": 1,
        "command": "models show",
        "model": profile.model_dump(mode="json"),
        "freshness": {
            "retrieved_at": profile.retrieved_at,
            "age_seconds": max(0, int((datetime.now(UTC) - profile.retrieved_at).total_seconds())),
            "stale": any(item.stale for item in profile.sources),
        },
        "observations": observation_summary.model_dump(mode="json") if observation_summary else None,
    }
    table = Table(title=profile.identity.canonical_id)
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Name", profile.identity.display_name or "unknown")
    table.add_row("Provider", profile.identity.provider)
    table.add_row("Context", str(profile.capabilities.context_length or "unknown"))
    table.add_row("Input modalities", ", ".join(profile.capabilities.input_modalities) or "unknown")
    table.add_row("Output modalities", ", ".join(profile.capabilities.output_modalities) or "unknown")
    table.add_row("Sources", ", ".join(source.name for source in profile.sources) or "unknown")
    table.add_row("Retrieved", _format_datetime(profile.retrieved_at))
    table.add_row("Pricing", _format_prices(profile))
    if observation_summary is not None:
        table.add_row("Observation samples", str(observation_summary.reliability.sample_count))
    _emit(payload, output_format, table)


@app.command()
def estimate(
    ctx: typer.Context,
    model: Annotated[Optional[str], typer.Option("--model", help="Canonical or provider-local model ID")] = None,
    filter: Annotated[Optional[str], typer.Option(help="Estimate every model whose ID/name contains this text")] = None,
    prompt: Annotated[Optional[str], typer.Option("--prompt", help="Prompt text to estimate")] = None,
    prompt_file: Annotated[Optional[Path], typer.Option("--prompt-file", exists=True, dir_okay=False)] = None,
    stdin: Annotated[bool, typer.Option("--stdin", help="Explicitly read the prompt from stdin")] = False,
    input_tokens: Annotated[Optional[int], typer.Option("--input-tokens", min=0)] = None,
    expected_output_tokens: Annotated[
        Optional[int], typer.Option("--expected-output-tokens", "--output-tokens", min=0)
    ] = None,
    input_modality: Annotated[Optional[list[str]], typer.Option("--input-modality")] = None,
    output_modality: Annotated[Optional[list[str]], typer.Option("--output-modality")] = None,
    minimum_context: Annotated[Optional[int], typer.Option("--minimum-context", min=0)] = None,
    requires_tools: Annotated[bool, typer.Option("--require-tools")] = False,
    requires_structured_output: Annotated[bool, typer.Option("--require-structured-output")] = False,
    requires_reasoning: Annotated[bool, typer.Option("--require-reasoning")] = False,
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Estimate per-component request cost for one or more catalog models."""
    modes = sum(value is not None for value in (prompt, prompt_file, input_tokens)) + int(stdin)
    if modes != 1:
        _fail(ctx, "Choose exactly one of --prompt, --prompt-file, --input-tokens, or --stdin.", 2)
    if prompt_file is not None:
        try:
            prompt = prompt_file.read_text(encoding="utf-8")
        except OSError as exc:
            _fail(ctx, f"Unable to read prompt file: {exc}", 2)
    if stdin:
        prompt = sys.stdin.read()
    try:
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
        profiles = list(snapshot.models.values())
        if model:
            profile = _find_profile(profiles, model)
            if profile is None:
                _fail(
                    ctx,
                    f"Model {model!r} was not found.",
                    2,
                    hint="Run `model-compass models list` to see available IDs.",
                )
            profiles = [profile]
        elif filter:
            key = filter.casefold()
            profiles = [
                item
                for item in profiles
                if key in item.identity.canonical_id.casefold() or key in (item.identity.display_name or "").casefold()
            ]
        else:
            _fail(ctx, "Specify --model or --filter.", 2)
        requirement_profile = RequestProfile(
            input_modalities=frozenset(input_modality or ()),
            output_modalities=frozenset(output_modality or ()),
            minimum_context=minimum_context,
            requires_tools=True if requires_tools else None,
            requires_structured_output=True if requires_structured_output else None,
            requires_reasoning=True if requires_reasoning else None,
        )
        profiles = [item for item in profiles if check_eligibility(item, requirement_profile).eligible]
        rows = []
        estimator = FallbackTokenEstimator()
        for profile in sorted(profiles, key=lambda item: item.identity.canonical_id):
            tokens = estimator.estimate(
                model=profile.identity.model_id,
                prompt=prompt,
                explicit_input_tokens=input_tokens,
                expected_output_tokens=expected_output_tokens,
            )
            request = RequestProfile(
                explicit_input_tokens=tokens.input_tokens,
                expected_output_tokens=tokens.output_tokens,
            )
            facade = _analytics(ctx)
            estimate_result = (
                facade.estimate_cost(profile, request)
                if hasattr(facade, "estimate_cost")
                else estimate_request_cost(profile, request)
            )
            rows.append(
                {
                    "model_id": profile.identity.canonical_id,
                    "input_tokens": tokens.input_tokens,
                    "output_tokens": tokens.output_tokens,
                    "token_estimate": tokens.model_dump(mode="json"),
                    "amount_usd": estimate_result.amount_usd,
                    "known_amount_usd": estimate_result.known_amount_usd,
                    "missing_components": estimate_result.missing_components,
                }
            )
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to estimate cost: {exc}", 4)
    if not rows:
        _fail(ctx, "No models matched the requested filter.", 3)
    payload: dict[str, Any] = {"schema_version": 1, "command": "estimate", "estimates": rows}
    if len(rows) == 1:
        payload.update(rows[0])
    table = Table(title="Estimated request cost")
    table.add_column("Model", style="bold")
    table.add_column("Input tokens")
    table.add_column("Output tokens")
    table.add_column("Input price")
    table.add_column("Output price")
    table.add_column("Estimated cost (USD)")
    for row in rows:
        profile = next(item for item in profiles if item.identity.canonical_id == row["model_id"])
        table.add_row(
            row["model_id"],
            str(row["input_tokens"]),
            str(row["output_tokens"]),
            _price(profile, "prompt"),
            _price(profile, "completion"),
            str(row["amount_usd"]) if row["amount_usd"] is not None else "unknown",
        )
    _emit(payload, output_format, table)


@app.command()
def compare(
    ctx: typer.Context,
    task: Annotated[str, typer.Option(help="Task label for empirical evidence")] = "general",
    prompt: Annotated[Optional[str], typer.Option("--prompt")] = None,
    input_tokens: Annotated[Optional[int], typer.Option("--input-tokens", min=0)] = None,
    output_tokens: Annotated[Optional[int], typer.Option("--expected-output-tokens", "--output-tokens", min=0)] = None,
    input_modality: Annotated[Optional[list[str]], typer.Option("--input-modality")] = None,
    output_modality: Annotated[Optional[list[str]], typer.Option("--output-modality")] = None,
    requires_tools: Annotated[bool, typer.Option("--require-tools", "--requires-tools")] = False,
    requires_structured_output: Annotated[
        bool, typer.Option("--require-structured-output", "--requires-structured-output")
    ] = False,
    requires_reasoning: Annotated[bool, typer.Option("--require-reasoning")] = False,
    minimum_context: Annotated[Optional[int], typer.Option("--minimum-context", min=0)] = None,
    min_quality: Annotated[Optional[str], typer.Option("--min-quality")] = None,
    max_cost: Annotated[Optional[str], typer.Option("--max-cost")] = None,
    max_latency_ms: Annotated[Optional[int], typer.Option("--max-latency-ms", min=0)] = None,
    min_reliability: Annotated[Optional[str], typer.Option("--min-reliability")] = None,
    include_model: Annotated[Optional[list[str]], typer.Option("--allow-model")] = None,
    exclude_model: Annotated[Optional[list[str]], typer.Option("--block-model")] = None,
    sort: Annotated[str, typer.Option(help="Policy: cheapest, best, fastest, most-reliable, cost-efficient")] = "best",
    limit: Annotated[Optional[int], typer.Option(min=1)] = None,
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Compare model eligibility, request cost, evidence, and ranking."""
    try:
        policy = SelectionPolicy(sort)
        request = _request(
            task=task,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_modalities=input_modality,
            output_modalities=output_modality,
            minimum_context=minimum_context,
            requires_tools=requires_tools,
            requires_structured_output=requires_structured_output,
            requires_reasoning=requires_reasoning,
            min_quality=_parse_decimal_option(min_quality, "--min-quality"),
            max_cost=_parse_decimal_option(max_cost, "--max-cost"),
            max_latency_ms=max_latency_ms,
            min_reliability=_parse_decimal_option(min_reliability, "--min-reliability"),
        )
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
        profiles = _model_inclusion(snapshot.models.values(), include_model, exclude_model)
        store = _store(ctx)
        report = compare_models(
            profiles,
            request,
            FallbackTokenEstimator(),
            prompt=prompt,
            observations=store.list(task=task),
            quality_evidence=store.list_quality_evidence(task=task),
            selected_policy=policy,
        )
    except StorageError as exc:
        _fail(ctx, f"Unable to compare models: {exc}", 6)
    except (ModelCompassError, ValueError) as exc:
        _fail(ctx, f"Unable to compare models: {exc}", 4 if isinstance(exc, ModelCompassError) else 2)
    candidates = list(report.candidates)
    candidates.sort(
        key=lambda candidate: (
            candidate.rank_by_policy.get(policy.value, sys.maxsize),
            candidate.model.identity.canonical_id,
        )
    )
    if limit is not None:
        candidates = candidates[:limit]
    payload = {
        "schema_version": 1,
        "command": "compare",
        "request": report.request.model_dump(mode="json"),
        "selected_policy": report.selected_policy.value if report.selected_policy else None,
        "candidates": [candidate.model_dump(mode="json") for candidate in candidates],
    }
    table = Table(title="Model comparison")
    table.add_column("Model", style="bold")
    table.add_column("Eligible")
    table.add_column("Cost (USD)")
    table.add_column("Quality")
    table.add_column("Latency")
    table.add_column("Reason")
    for candidate in candidates:
        table.add_row(
            candidate.model.identity.canonical_id,
            "yes" if candidate.eligibility.eligible else "no",
            str(candidate.cost.total) if candidate.cost.complete else "unknown",
            str(candidate.quality_evidence.value) if candidate.quality_evidence else "unknown",
            str(candidate.latency_evidence.value) if candidate.latency_evidence else "unknown",
            "; ".join(candidate.eligibility.reasons) or "eligible",
        )
    _emit(payload, output_format, table)


@app.command()
def select(
    ctx: typer.Context,
    task: Annotated[str, typer.Option(help="Task label for empirical evidence")] = "general",
    input_tokens: Annotated[Optional[int], typer.Option("--input-tokens", min=0)] = None,
    output_tokens: Annotated[Optional[int], typer.Option("--expected-output-tokens", "--output-tokens", min=0)] = None,
    input_modality: Annotated[Optional[list[str]], typer.Option("--input-modality")] = None,
    output_modality: Annotated[Optional[list[str]], typer.Option("--output-modality")] = None,
    minimum_context: Annotated[Optional[int], typer.Option("--minimum-context", min=0)] = None,
    max_cost: Annotated[Optional[str], typer.Option("--max-cost")] = None,
    min_quality: Annotated[Optional[str], typer.Option("--min-quality")] = None,
    max_latency_ms: Annotated[Optional[int], typer.Option("--max-latency-ms", min=0)] = None,
    min_reliability: Annotated[Optional[str], typer.Option("--min-reliability")] = None,
    requires_tools: Annotated[bool, typer.Option("--require-tools")] = False,
    requires_structured_output: Annotated[bool, typer.Option("--require-structured-output")] = False,
    requires_reasoning: Annotated[bool, typer.Option("--require-reasoning")] = False,
    objective: Annotated[SelectionPolicy, typer.Option("--objective", "--policy")] = SelectionPolicy.BEST,
    allow_model: Annotated[Optional[list[str]], typer.Option("--allow-model")] = None,
    block_model: Annotated[Optional[list[str]], typer.Option("--block-model")] = None,
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Select an eligible model without executing it."""
    try:
        request = _request(
            task=task,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            input_modalities=input_modality,
            output_modalities=output_modality,
            minimum_context=minimum_context,
            requires_tools=requires_tools,
            requires_structured_output=requires_structured_output,
            requires_reasoning=requires_reasoning,
            min_quality=_parse_decimal_option(min_quality, "--min-quality"),
            max_cost=_parse_decimal_option(max_cost, "--max-cost"),
            max_latency_ms=max_latency_ms,
            min_reliability=_parse_decimal_option(min_reliability, "--min-reliability"),
        )
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
        profiles = _model_inclusion(snapshot.models.values(), allow_model, block_model)
        result = _analytics(ctx).select(profiles, request, policy=objective)
    except NoEligibleModelError as exc:
        _fail(ctx, f"No eligible model: {exc}", 3)
    except (ModelCompassError, ValueError) as exc:
        _fail(ctx, f"Unable to select a model: {exc}", 4 if isinstance(exc, ModelCompassError) else 2)
    payload = {
        "schema_version": 1,
        "command": "select",
        "selected": result.selected.model_dump(mode="json") if result.selected else None,
        "policy": result.policy.value,
        "expected_cost_usd": result.selected.expected_cost_usd if result.selected else None,
        "quality_evidence": result.selected.quality_evidence.model_dump(mode="json")
        if result.selected and result.selected.quality_evidence
        else None,
        "latency_evidence": result.selected.latency_evidence.model_dump(mode="json")
        if result.selected and result.selected.latency_evidence
        else None,
        "reliability_evidence": result.selected.reliability_evidence.model_dump(mode="json")
        if result.selected and result.selected.reliability_evidence
        else None,
        "constraints": request.model_dump(mode="json"),
        "allowed_models": allow_model or [],
        "blocked_models": block_model or [],
        "explanation": result.human_summary(),
        "alternatives": [item.model_dump(mode="json") for item in result.ranked[1:4]],
        "assessments": [item.model_dump(mode="json") for item in result.assessments],
    }
    table = Table(title=f"Model selection ({result.policy.value})")
    table.add_column("Model", style="bold")
    table.add_column("Selected")
    table.add_column("Eligible")
    table.add_column("Quality")
    table.add_column("Cost (USD)")
    table.add_column("Rejection reason")
    for item in result.assessments:
        table.add_row(
            item.model_id,
            "yes" if result.selected and item.model_id == result.selected.model_id else "",
            "yes" if item.eligible else "no",
            str(item.quality) if item.quality is not None else "unknown",
            str(item.expected_cost_usd) if item.expected_cost_usd is not None else "unknown",
            "; ".join(item.reasons),
        )
    if result.selected:
        table.caption = result.human_summary()
    _emit(payload, output_format, table)
    if result.selected is None:
        raise typer.Exit(code=3)


@app.command()
def pareto(
    ctx: typer.Context,
    objectives: Annotated[
        Optional[str], typer.Option("--objectives", help="Legacy comma-separated objective dimensions")
    ] = None,
    objective: Annotated[
        Optional[list[str]],
        typer.Option("--objective", help="Objective and direction, e.g. quality:max (repeatable)"),
    ] = None,
    task: Annotated[str, typer.Option(help="Task label for empirical evidence")] = "general",
    input_tokens: Annotated[Optional[int], typer.Option("--input-tokens", min=0)] = None,
    output_tokens: Annotated[Optional[int], typer.Option("--expected-output-tokens", "--output-tokens", min=0)] = None,
    include_dominated: Annotated[
        bool, typer.Option(help="Include eligible models dominated by frontier members")
    ] = False,
    offline: Annotated[bool, typer.Option(help="Use cached catalog data only")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Show a Pareto frontier for quality, cost, latency, and reliability."""
    try:
        selected_objectives = _pareto_objectives(objective, objectives)
    except ValueError as exc:
        _fail(ctx, f"Unable to calculate Pareto frontier: {exc}", 2)
    try:
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
        result = _analytics(ctx).select(
            list(snapshot.models.values()),
            RequestProfile(task=task, explicit_input_tokens=input_tokens, expected_output_tokens=output_tokens),
        )
        analysis = pareto_analysis(result.assessments, selected_objectives)
    except (ModelCompassError, ValueError) as exc:
        _fail(ctx, f"Unable to calculate Pareto frontier: {exc}", 4 if isinstance(exc, ModelCompassError) else 2)
    members = analysis.frontier
    if include_dominated:
        by_id = {item.model_id: item for item in result.assessments}
        members = tuple(by_id[key] for key in sorted(by_id) if by_id[key].eligible)
    payload = {
        "schema_version": 1,
        "command": "pareto",
        "objectives": [
            f"{key.value}:{'max' if value == ObjectiveDirection.MAXIMIZE else 'min'}"
            for key, value in selected_objectives.items()
        ],
        "frontier": [item.model_dump(mode="json") for item in analysis.frontier],
        "dominated_by": analysis.dominated_by,
        "models": [item.model_dump(mode="json") for item in members],
    }
    table = Table(title="Pareto frontier" if not include_dominated else "Pareto analysis")
    table.add_column("Model", style="bold")
    table.add_column("Frontier")
    table.add_column("Quality")
    table.add_column("Reliability")
    table.add_column("Cost (USD)")
    table.add_column("Latency (ms)")
    for item in members:
        table.add_row(
            item.model_id,
            "yes" if item in analysis.frontier else "no",
            str(item.quality) if item.quality is not None else "unknown",
            str(item.reliability) if item.reliability is not None else "unknown",
            str(item.expected_cost_usd) if item.expected_cost_usd is not None else "unknown",
            str(item.latency_ms) if item.latency_ms is not None else "unknown",
        )
    _emit(payload, output_format, table)


@observations_app.callback()
def observations_callback(
    ctx: typer.Context,
    task: Annotated[Optional[str], typer.Option(help="Filter by exact task label")] = None,
    model_id: Annotated[Optional[str], typer.Option("--model", help="Filter by model ID")] = None,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Inspect, summarize, export, or import recorded observations."""
    if ctx.invoked_subcommand is None:
        _observations_list(ctx, task=task, model_id=model_id, output_format=output_format)


@observations_app.command("stats")
def observations_stats(
    ctx: typer.Context,
    model: Annotated[Optional[str], typer.Option("--model")] = None,
    task: Annotated[Optional[str], typer.Option("--task")] = None,
    since: Annotated[Optional[str], typer.Option(help="Include records at or after ISO-8601 timestamp")] = None,
    gateway: Annotated[Optional[str], typer.Option(help="Filter by gateway/provider substring")] = None,
    provider: Annotated[Optional[str], typer.Option(help="Filter by provider substring")] = None,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Summarize observations and report the exact sample count."""
    try:
        since_dt = _parse_datetime(since) if since else None
        rows = _store(ctx).query_observations(model_id=model, task=task, since=since_dt)
        if gateway:
            rows = [item for item in rows if gateway.casefold() in (item.gateway or "").casefold()]
        if provider:
            rows = [item for item in rows if provider.casefold() in (item.provider or "").casefold()]
        summary = summarize_observations(rows, min_samples=1)
    except (ModelCompassError, ValueError) as exc:
        _fail(ctx, f"Unable to summarize observations: {exc}", 6 if isinstance(exc, ModelCompassError) else 2)
    payload = {
        "schema_version": 1,
        "command": "observations stats",
        "filters": {"model": model, "task": task, "since": since, "gateway": gateway, "provider": provider},
        "sample_count": len(rows),
        "summary": summary.model_dump(mode="json"),
    }
    table = Table(title="Observation statistics")
    table.add_column("Metric", style="bold")
    table.add_column("Value")
    table.add_row("Samples", str(len(rows)))
    table.add_row("Successes", str(summary.reliability.success_count))
    table.add_row("Success rate", _unknown(summary.reliability.success_rate))
    table.add_row("Mean latency (ms)", _unknown(summary.latency.mean_latency_ms))
    table.add_row("Mean actual cost (USD)", _unknown(summary.cost.mean_actual_cost))
    _emit(payload, output_format, table)


@observations_app.command("export")
def observations_export(
    ctx: typer.Context,
    output: Annotated[Path, typer.Option("--output", help="Destination JSONL path")],
):
    """Export observations and benchmark results in the stable JSONL format."""
    try:
        output.write_text(_store(ctx).export_jsonl(), encoding="utf-8")
    except (ModelCompassError, OSError) as exc:
        _fail(ctx, f"Unable to export observations: {exc}", 6)
    console.print(f"Exported JSONL to {output}")


@observations_app.command("import")
def observations_import(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(exists=True, dir_okay=False, readable=True)],
    deduplicate: Annotated[bool, typer.Option(help="Skip records already present in the database")] = False,
):
    """Validate and import records from a JSONL file."""
    try:
        content = source.read_text(encoding="utf-8")
        imported = _store(ctx).import_jsonl(content, deduplicate=deduplicate)
    except (ModelCompassError, OSError) as exc:
        _fail(ctx, f"Unable to import observations: {exc}", 6)
    console.print(f"Imported {imported} records")


@benchmark_app.callback()
def benchmark_callback(
    ctx: typer.Context,
    dataset: Annotated[Optional[Path], typer.Option("--dataset", exists=True, dir_okay=False)] = None,
    outputs: Annotated[Optional[Path], typer.Option("--outputs", exists=True, dir_okay=False)] = None,
    model: Annotated[Optional[str], typer.Option("--model")] = None,
    record: Annotated[bool, typer.Option(help="Persist offline evaluation as quality evidence")] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Run, inspect, and export benchmarks; bare ``benchmark`` scores saved outputs."""
    if ctx.invoked_subcommand is None and dataset and outputs and model:
        _benchmark_offline(ctx, dataset, outputs, model, record=record, output_format=output_format)
    elif ctx.invoked_subcommand is None:
        console.print(ctx.get_help())


@benchmark_app.command("run")
def benchmark_run(
    ctx: typer.Context,
    dataset: Annotated[Path, typer.Option("--dataset", exists=True, dir_okay=False, readable=True)],
    model: Annotated[list[str], typer.Option("--model", help="Model ID (repeatable)")],
    repetitions: Annotated[int, typer.Option(min=1)] = 1,
    concurrency: Annotated[int, typer.Option(min=1)] = 1,
    evaluator: Annotated[Optional[str], typer.Option(help="Override evaluator for all cases")] = None,
    max_cost: Annotated[Optional[str], typer.Option("--max-cost", help="Maximum total advisory budget in USD")] = None,
    acknowledge_live: Annotated[
        bool,
        typer.Option(
            "--acknowledge-live", help="Required: this command sends live requests and may incur provider charges"
        ),
    ] = False,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Run a live benchmark against providers (explicit acknowledgement required)."""
    if not acknowledge_live:
        _fail(ctx, "Live benchmark not started.", 2, hint="Pass --acknowledge-live to permit billable model requests.")
    try:
        max_cost = _parse_decimal_option(max_cost, "--max-cost")
    except ValueError as exc:
        _fail(ctx, f"Benchmark failed: {exc}", 2)
    try:
        content = dataset.read_text(encoding="utf-8")
        dataset_model = load_dataset_jsonl(content)
        if evaluator:
            dataset_model = dataset_model.model_copy(
                update={
                    "cases": tuple(case.model_copy(update={"evaluator": evaluator}) for case in dataset_model.cases)
                }
            )
        budget = RunnerBudget(max_total_cost=max_cost) if max_cost is not None else None
        outcome = asyncio.run(
            run_benchmark(
                dataset_model,
                model,
                backend=LiteLLMBackend(),
                config=BenchmarkRunConfig(repetitions=repetitions, concurrency=concurrency, budget=budget),
            )
        )
    except (ModelCompassError, OSError, ValueError) as exc:
        _fail(ctx, f"Benchmark failed: {exc}", 5)
    try:
        store = _store(ctx)
        store.record_benchmark_run(outcome.run)
        for result in _aggregate_benchmark_results(outcome.results):
            store.record_benchmark_result(result)
    except (StorageError, sqlite3.Error) as exc:
        _fail(ctx, f"Unable to persist benchmark results: {exc}", 6)
    payload = {
        "schema_version": 1,
        "command": "benchmark run",
        "run": outcome.run.model_dump(mode="json"),
        "results": [item.model_dump(mode="json") for item in outcome.results],
        "result_count": len(outcome.results),
    }
    table = Table(title=f"Benchmark run {outcome.run.run_id}")
    table.add_column("Model", style="bold")
    table.add_column("Cases")
    table.add_column("Scored")
    for model_id in model:
        matching = [item for item in outcome.results if item.model_id == model_id]
        table.add_row(model_id, str(len(matching)), str(sum(item.score is not None for item in matching)))
    _emit(payload, output_format, table)


@benchmark_app.command("list")
def benchmark_list(
    ctx: typer.Context,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """List stored benchmark runs."""
    try:
        runs = _store(ctx).query_benchmark_runs()
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to list benchmark runs: {exc}", 6)
    payload = {
        "schema_version": 1,
        "command": "benchmark list",
        "runs": [item.model_dump(mode="json") for item in runs],
    }
    table = Table(title="Benchmark runs")
    table.add_column("Run ID", style="bold")
    table.add_column("Dataset")
    table.add_column("Status")
    table.add_column("Started")
    for item in runs:
        table.add_row(item.run_id, item.dataset_id, item.status, _format_datetime(item.started_at))
    _emit(payload, output_format, table)


@benchmark_app.command("show")
def benchmark_show(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Stored benchmark run ID")],
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Show one stored run and its per-case results."""
    try:
        store = _store(ctx)
        run = next((item for item in store.query_benchmark_runs() if item.run_id == run_id), None)
        if run is None:
            _fail(ctx, f"Benchmark run {run_id!r} was not found.", 2)
        results = store.query_benchmark_results(run_id=run_id)
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to read benchmark run: {exc}", 6)
    payload = {
        "schema_version": 1,
        "command": "benchmark show",
        "run": run.model_dump(mode="json"),
        "results": [item.model_dump(mode="json") for item in results],
    }
    table = Table(title=f"Benchmark {run_id}")
    table.add_column("Case", style="bold")
    table.add_column("Model")
    table.add_column("Score")
    table.add_column("Cost (USD)")
    for item in results:
        table.add_row(item.case_id, item.model_id, _unknown(item.score), _unknown(item.cost))
    _emit(payload, output_format, table)


@benchmark_app.command("export")
def benchmark_export(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Option("--run-id")],
    output: Annotated[Path, typer.Option("--output")],
):
    """Export a stored benchmark run and its results as versioned JSON."""
    try:
        store = _store(ctx)
        run = next((item for item in store.query_benchmark_runs() if item.run_id == run_id), None)
        if run is None:
            _fail(ctx, f"Benchmark run {run_id!r} was not found.", 2)
        results = store.query_benchmark_results(run_id=run_id)
        output.write_text(
            json.dumps(
                _json_value(
                    {
                        "schema_version": 1,
                        "command": "benchmark export",
                        "run": run.model_dump(mode="python"),
                        "results": [item.model_dump(mode="python") for item in results],
                    }
                ),
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
    except (ModelCompassError, OSError) as exc:
        _fail(ctx, f"Unable to export benchmark: {exc}", 6)
    console.print(f"Exported benchmark run to {output}")


@db_app.command("status")
def db_status(
    ctx: typer.Context,
    output_format: Annotated[OutputFormat, typer.Option("--format")] = OutputFormat.table,
):
    """Report the configured database path without creating it."""
    path = _db_path(ctx)
    payload = {
        "schema_version": 1,
        "command": "db status",
        "path": str(path),
        "exists": path.is_file(),
        "size_bytes": path.stat().st_size if path.is_file() else None,
    }
    table = Table(title="Database status")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Path", str(path))
    table.add_row("Exists", str(path.is_file()).lower())
    table.add_row("Size", f"{path.stat().st_size} bytes" if path.is_file() else "not created")
    _emit(payload, output_format, table)


@db_app.command("vacuum")
def db_vacuum(ctx: typer.Context):
    """Reclaim unused space in the configured SQLite database."""
    try:
        _store(ctx).vacuum()
    except (ModelCompassError, sqlite3.Error) as exc:
        _fail(ctx, f"Unable to vacuum database: {exc}", 6)
    console.print("Database vacuum complete")


@app.command()
def run(
    ctx: typer.Context,
    model_id: Annotated[str, typer.Option("--model", help="LiteLLM model identifier")],
    task: Annotated[str, typer.Option(help="Task label for recorded observations")] = "general",
    stdin: Annotated[bool, typer.Option("--stdin", help="Explicitly read the prompt from stdin")] = False,
):
    """Execute one request and record aggregate usage; prompt input is explicit."""
    if not stdin:
        _fail(ctx, "A prompt source is required.", 2, hint="Pass --stdin and pipe or enter prompt text.")
    prompt = sys.stdin.read()
    if not prompt:
        _fail(ctx, "Provide a prompt on stdin.", 2)
    try:
        result = asyncio.run(
            _analytics(ctx).execute(
                CompletionRequest(model_id=model_id, task=task, messages=[{"role": "user", "content": prompt}])
            )
        )
    except StorageError as exc:
        _fail(ctx, f"Unable to record execution observation: {exc}", 6)
    except ModelCompassError as exc:
        _fail(ctx, f"Execution failed: {exc}", 5)
    print(result.output_text)


app.add_typer(config_app, name="config")
app.add_typer(catalog_app, name="catalog")
app.add_typer(models_app, name="models")
app.add_typer(observations_app, name="observations")
app.add_typer(benchmark_app, name="benchmark")
app.add_typer(db_app, name="db")


def _models_list(
    ctx: typer.Context,
    *,
    source: Optional[str] = None,
    gateway: Optional[str] = None,
    modality: Optional[str] = None,
    tools: bool = False,
    structured_output: bool = False,
    reasoning: bool = False,
    minimum_context: Optional[int] = None,
    free_only: bool = False,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    offline: bool = False,
    output_format: OutputFormat = OutputFormat.table,
):
    """Filter normalized catalog profiles and render compact model rows."""
    try:
        snapshot, _ = _refresh_catalog(ctx, source="all", offline=offline)
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to load catalog: {exc}", 4)
    profiles = list(snapshot.models.values())
    if source:
        profiles = [item for item in profiles if any(source.casefold() in x.name.casefold() for x in item.sources)]
    if gateway:
        profiles = [
            item
            for item in profiles
            if gateway.casefold() in item.identity.provider.casefold()
            or any(gateway.casefold() in endpoint.provider.casefold() for endpoint in item.endpoints)
        ]
    if modality:
        modality = modality.casefold()
        if modality not in {"text", "vision", "audio", "video"}:
            _fail(ctx, "Modality must be text, vision, audio, or video.", 2)
        profiles = [
            item
            for item in profiles
            if modality in item.capabilities.input_modalities + item.capabilities.output_modalities
            or (modality == "vision" and item.capabilities.image.value == "supported")
        ]
    if tools:
        profiles = [item for item in profiles if item.capabilities.tools.value == "supported"]
    if structured_output:
        profiles = [item for item in profiles if item.capabilities.structured_output.value == "supported"]
    if reasoning:
        profiles = [item for item in profiles if item.capabilities.reasoning.value == "supported"]
    if minimum_context is not None:
        profiles = [
            item
            for item in profiles
            if item.capabilities.context_length is not None and item.capabilities.context_length >= minimum_context
        ]
    if free_only:
        profiles = [item for item in profiles if _known_free(item)]
    if search:
        needle = search.casefold()
        profiles = [
            item
            for item in profiles
            if needle in item.identity.canonical_id.casefold()
            or needle in (item.identity.display_name or "").casefold()
        ]
    profiles.sort(key=lambda item: item.identity.canonical_id)
    if limit is not None:
        profiles = profiles[:limit]
    rows = [_model_list_row(item) for item in profiles]
    payload = {"schema_version": 1, "command": "models list", "models": rows}
    table = Table(title="Available models")
    for column in (
        "Model",
        "Context",
        "Modalities",
        "Tools",
        "Structured",
        "Input price",
        "Output price",
        "Source age",
    ):
        table.add_column(column, style="bold" if column == "Model" else None)
    for row in rows:
        table.add_row(
            row["model"],
            row["context"],
            row["modalities"],
            row["tools"],
            row["structured"],
            row["input_price"],
            row["output_price"],
            row["source_age"],
        )
    _emit(payload, output_format, table)


def _observations_list(
    ctx: typer.Context,
    *,
    task: Optional[str],
    model_id: Optional[str],
    output_format: OutputFormat,
):
    """List aggregate execution observations in the selected output format."""
    try:
        records = _analytics(ctx).list_observations(model_id=model_id, task=task)
    except ModelCompassError as exc:
        _fail(ctx, f"Unable to read observations: {exc}", 6)
    payload = {
        "schema_version": 1,
        "command": "observations list",
        "observations": [item.model_dump(mode="json") for item in records],
    }
    table = Table(title="Execution observations")
    table.add_column("Model", style="bold")
    table.add_column("Task")
    table.add_column("Success")
    table.add_column("Latency (ms)")
    table.add_column("Cost (USD)")
    for item in records:
        table.add_row(
            item.model_id,
            item.task or "",
            "yes" if item.succeeded else "no",
            _unknown(item.latency_ms),
            _unknown(item.actual_cost_usd),
        )
    _emit(payload, output_format, table)


def _benchmark_offline(
    ctx: typer.Context,
    dataset: Path,
    outputs: Path,
    model_id: str,
    *,
    record: bool,
    output_format: OutputFormat,
):
    """Evaluate saved benchmark outputs without invoking a model."""
    try:
        dataset_model = load_dataset_jsonl(dataset.read_text(encoding="utf-8"))
        output_payload = json.loads(outputs.read_text(encoding="utf-8"))
        if not isinstance(output_payload, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in output_payload.items()
        ):
            raise ValueError("outputs file must contain a JSON object of string case IDs to strings")
        report = evaluate_offline(dataset_model, output_payload, model_id=model_id)
        if record:
            _analytics(ctx).record_benchmark(report)
    except StorageError as exc:
        _fail(ctx, f"Unable to store benchmark evidence: {exc}", 6)
    except (ModelCompassError, OSError, ValueError) as exc:
        _fail(ctx, f"Unable to evaluate benchmark: {exc}", 5)
    payload = {"schema_version": 1, "command": "benchmark", **report.model_dump(mode="json")}
    table = Table(title=f"Benchmark: {report.dataset} ({report.task})")
    table.add_column("Model", style="bold")
    table.add_column("Score")
    table.add_column("Samples")
    table.add_column("Passed")
    table.add_row(report.model_id, str(report.quality_score), str(report.sample_size), str(report.passed))
    _emit(payload, output_format, table)


def _refresh_catalog(
    ctx: typer.Context, *, source: str, force: bool = False, offline: bool = False
) -> tuple[CatalogSnapshot, str]:
    """Refresh a selected catalog source through the catalog service."""
    if source not in {"all", "openrouter", "litellm"}:
        raise ValueError("source must be openrouter, litellm, or all")
    service = _analytics(ctx).catalog
    if source == "litellm":
        adapter = LiteLLMCatalogAdapter()
        snapshot = asyncio.run(adapter.refresh(force=force, offline=offline))
        return snapshot, source
    return service.refresh(force=force, offline=offline, include_litellm=source == "all"), source


def _analytics(ctx: typer.Context) -> Any:
    """Return the analytics facade configured for this CLI invocation."""
    options = ctx.find_root().obj
    if options["analytics"] is not None:
        return options["analytics"]
    if any(options[key] is not None for key in ("data_dir", "cache_dir", "db")):
        paths = _effective_paths(ctx)
        service = CatalogService(
            openrouter_provider=OpenRouterCatalogAdapter(cache_dir=paths.cache_dir / "catalog"),
            litellm_provider=LiteLLMCatalogAdapter(),
        )
        options["analytics"] = AnalyticsFacade(catalog=service, observation_store=_store(ctx))
    else:
        options["analytics"] = analytics
    return options["analytics"]


def _store(ctx: typer.Context) -> SQLiteObservationStore:
    """Return the lazily initialized store for the selected database path."""
    options = ctx.find_root().obj
    if options["store"] is None:
        options["store"] = SQLiteObservationStore(_db_path(ctx))
    return options["store"]


def _db_path(ctx: typer.Context) -> Path:
    """Resolve the configured or platform-default SQLite database path."""
    options = ctx.find_root().obj
    if options["db"] is not None:
        return options["db"]
    data_dir = options["data_dir"] or default_paths().data_dir
    return data_dir / "observations.sqlite3"


def _effective_paths(ctx: typer.Context) -> AppPaths:
    """Resolve path overrides without creating data or cache directories."""
    options = ctx.find_root().obj
    defaults = default_paths()
    data_dir = options["data_dir"] or defaults.data_dir
    return AppPaths(
        config_dir=defaults.config_dir,
        data_dir=data_dir,
        cache_dir=options["cache_dir"] or defaults.cache_dir,
    )


def _path_data(paths: AppPaths) -> dict[str, str]:
    """Convert effective paths to their public display and JSON representation."""
    return {
        "config_dir": str(paths.config_dir),
        "data_dir": str(paths.data_dir),
        "cache_dir": str(paths.cache_dir),
    }


def _request(
    *,
    task: str,
    input_tokens: Optional[int],
    output_tokens: Optional[int],
    input_modalities: Optional[list[str]],
    output_modalities: Optional[list[str]],
    minimum_context: Optional[int],
    requires_tools: bool,
    requires_structured_output: bool,
    requires_reasoning: bool,
    min_quality: Optional[Decimal],
    max_cost: Optional[Decimal],
    max_latency_ms: Optional[int],
    min_reliability: Optional[Decimal],
) -> RequestProfile:
    """Build a validated request profile from CLI options."""
    return RequestProfile(
        task=task,
        explicit_input_tokens=input_tokens,
        expected_output_tokens=output_tokens,
        input_modalities=frozenset(input_modalities or ()),
        output_modalities=frozenset(output_modalities or ()),
        minimum_context=minimum_context,
        requires_tools=True if requires_tools else None,
        requires_structured_output=True if requires_structured_output else None,
        requires_reasoning=True if requires_reasoning else None,
        min_quality=min_quality,
        max_cost_usd=max_cost,
        max_latency_ms=max_latency_ms,
        min_reliability=min_reliability,
    )


def _pareto_objectives(
    values: Optional[list[str]],
    legacy_values: Optional[str] = None,
) -> dict[ParetoObjective, ObjectiveDirection]:
    """Parse directional Pareto objectives or legacy dimension names."""
    if legacy_values is not None:
        values = []
        for item in legacy_values.split(","):
            name = item.strip()
            direction = "max" if name in {"quality", "reliability"} else "min"
            values.append(f"{name}:{direction}")
    if not values:
        return {
            ParetoObjective.QUALITY: ObjectiveDirection.MAXIMIZE,
            ParetoObjective.COST: ObjectiveDirection.MINIMIZE,
        }
    objectives: dict[ParetoObjective, ObjectiveDirection] = {}
    for value in values:
        try:
            name, direction = value.split(":", maxsplit=1)
            normalized_direction = {"min": "minimize", "max": "maximize"}.get(direction, direction)
            objectives[ParetoObjective(name)] = ObjectiveDirection(normalized_direction)
        except (ValueError, TypeError) as exc:
            raise ValueError(f"invalid Pareto objective {value!r}; use dimension:min or dimension:max") from exc
    return objectives


def _model_inclusion(
    profiles: Iterable[ModelProfile],
    included: Optional[list[str]],
    excluded: Optional[list[str]],
) -> list[ModelProfile]:
    """Apply explicit model allow and block lists."""
    include_values = {value.casefold() for value in included or ()}
    exclude_values = {value.casefold() for value in excluded or ()}
    return [
        item
        for item in profiles
        if (not include_values or item.identity.canonical_id.casefold() in include_values)
        and item.identity.canonical_id.casefold() not in exclude_values
    ]


def _model_list_row(profile: ModelProfile) -> dict[str, Any]:
    """Convert a profile to compact model-list output."""
    capabilities = profile.capabilities
    modalities = sorted(set(capabilities.input_modalities + capabilities.output_modalities))
    return {
        "model": profile.identity.canonical_id,
        "context": str(capabilities.context_length) if capabilities.context_length is not None else "?",
        "modalities": ", ".join(modalities) or "?",
        "tools": capabilities.tools.value,
        "structured": capabilities.structured_output.value,
        "input_price": _price(profile, "prompt"),
        "output_price": _price(profile, "completion"),
        "source_age": _format_age(profile.retrieved_at),
        "pricing": {key: str(component.amount) for key, component in sorted(profile.pricing.components.items())},
    }


def _catalog_table(snapshot: Any) -> Table:
    """Build a compact catalog status table."""
    table = Table(title="Catalog refresh")
    table.add_column("Property", style="bold")
    table.add_column("Value")
    table.add_row("Models", str(len(snapshot.models)))
    table.add_row("Retrieved", _format_datetime(snapshot.retrieved_at))
    table.add_row("Stale", str(snapshot.stale).lower())
    return table


def _known_free(profile: ModelProfile) -> bool:
    """Return whether known input and output token prices are both zero."""
    input_price = profile.pricing.components.get("prompt")
    output_price = profile.pricing.components.get("completion")
    return input_price is not None and output_price is not None and input_price.amount == 0 and output_price.amount == 0


def _price(profile: ModelProfile, key: str) -> str:
    """Format a normalized price or return ``unknown``."""
    component = profile.pricing.components.get(key)
    return str(component.amount) if component is not None else "unknown"


def _format_prices(profile: ModelProfile) -> str:
    """Format every normalized price component for detailed model output."""
    components = profile.pricing.effective_components()
    return (
        ", ".join(f"{key}={value.amount} {value.currency}/{value.unit}" for key, value in sorted(components.items()))
        or "unknown"
    )


def _find_profile(profiles: Iterable[ModelProfile], requested_id: str) -> Optional[ModelProfile]:
    """Find a profile by canonical or provider-local ID, case-insensitively."""
    lowered = requested_id.strip().casefold()
    return next(
        (
            profile
            for profile in profiles
            if profile.identity.canonical_id.casefold() == lowered or profile.identity.model_id.casefold() == lowered
        ),
        None,
    )


def _parse_decimal_option(value: Optional[str], option_name: str) -> Optional[Decimal]:
    """Parse a finite decimal CLI value without binary floating-point conversion."""
    if value is None:
        return None
    try:
        result = Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{option_name} must be a decimal number") from exc
    if not result.is_finite():
        raise ValueError(f"{option_name} must be a finite decimal number")
    return result


def _aggregate_benchmark_results(results: Iterable[BenchmarkResult]) -> tuple[BenchmarkResult, ...]:
    """Aggregate repeated case/model results while retaining each repetition in metadata."""
    grouped: dict[tuple[str, str, str], list[BenchmarkResult]] = {}
    for result in results:
        grouped.setdefault((result.run_id, result.case_id, result.model_id), []).append(result)

    aggregated: list[BenchmarkResult] = []
    for identity in sorted(grouped):
        repetitions = sorted(
            grouped[identity],
            key=lambda item: (item.metadata.get("repetition", sys.maxsize), item.model_dump_json()),
        )
        if len(repetitions) == 1:
            aggregated.append(repetitions[0])
            continue

        first = repetitions[0]
        metadata = {
            **first.metadata,
            "repetition_count": len(repetitions),
            "repetitions": [item.model_dump(mode="json") for item in repetitions],
        }
        aggregated.append(
            first.model_copy(
                update={
                    "score": _mean_decimal(item.score for item in repetitions),
                    "cost": _mean_decimal(item.cost for item in repetitions),
                    "latency_ms": _mean_decimal(item.latency_ms for item in repetitions),
                    "metadata": metadata,
                }
            )
        )
    return tuple(aggregated)


def _mean_decimal(values: Iterable[Optional[Decimal]]) -> Optional[Decimal]:
    """Return the Decimal mean of present values, or None when no values are present."""
    present = [value for value in values if value is not None]
    return sum(present, Decimal(0)) / Decimal(len(present)) if present else None


def _parse_datetime(value: str) -> datetime:
    """Parse an ISO-8601 timestamp and require an explicit timezone."""
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("timestamp must be ISO-8601") from exc
    if result.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return result.astimezone(UTC)


def _emit(payload: Mapping[str, Any], output_format: OutputFormat, table: Table):
    """Render structured JSON or its corresponding Rich table."""
    if output_format == OutputFormat.json:
        _print_json(payload)
    else:
        console.print(table)


def _print_json(payload: Mapping[str, Any]):
    """Print JSON without Rich markup processing."""
    print(json.dumps(_json_value(payload), indent=2, sort_keys=True, ensure_ascii=False))


def _json_value(value: Any) -> Any:
    """Recursively encode Pydantic and standard-library values as JSON-safe data."""
    if isinstance(value, BaseModel):
        return _json_value(value.model_dump(mode="python"))
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _format_datetime(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_json_value(item) for item in value]
    return value


def _fail(
    ctx: typer.Context,
    message: str,
    code: int,
    *,
    hint: Optional[str] = None,
) -> NoReturn:
    """Print a concise diagnostic and exit with a stable CLI code."""
    try:
        exit_code = ExitCode(code)
    except ValueError:
        exit_code = ExitCode.CLI_ERROR
    err_console.print(f"Error: {message}")
    if hint:
        err_console.print(f"Hint: {hint}")
    if ctx.find_root().obj.get("debug"):
        traceback.print_exc(file=sys.stderr)
    raise typer.Exit(code=int(exit_code))


def _format_datetime(value: Optional[datetime]) -> str:
    """Format an optional datetime as UTC ISO-8601."""
    if value is None:
        return "unknown"
    normalized = value.astimezone(UTC)
    return normalized.isoformat().replace("+00:00", "Z")


def _format_age(value: datetime) -> str:
    """Format the elapsed age of catalog data."""
    seconds = max(0, int((datetime.now(UTC) - value).total_seconds()))
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m"
    return f"{seconds // 3600}h"


def _unknown(value: Any) -> str:
    """Render missing measurements as ``unknown`` instead of zero."""
    return str(value) if value is not None else "unknown"


__all__ = ["app"]
