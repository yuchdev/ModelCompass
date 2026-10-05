"""CLI entry points for model-compass."""

from __future__ import annotations

import asyncio
import json
import platform
import sys
from collections.abc import Iterable
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from model_compass import __version__
from model_compass.application import analytics
from model_compass.benchmarks import BenchmarkDataset, evaluate_benchmark
from model_compass.config import default_paths
from model_compass.domain import ModelProfile, RequestProfile
from model_compass.exceptions import ModelCompassError
from model_compass.execution import CompletionRequest
from model_compass.selection import (
    ParetoObjective,
    SelectionPolicy,
    estimate_cost,
    pareto_frontier,
)

app = typer.Typer(
    name="model-compass",
    help="Request-aware LLM model analytics, comparison, and selection.",
    no_args_is_help=True,
)

console = Console()
err_console = Console(stderr=True)


class OutputFormat(StrEnum):
    """Supported CLI output formats."""

    table = "table"
    json = "json"


@app.command()
def version() -> None:
    """Print the installed package version."""
    console.print(__version__)


@app.command()
def doctor(
    output_format: Annotated[
        OutputFormat,
        typer.Option("--format", help="Output format: table or json"),
    ] = OutputFormat.table,
) -> None:
    """Report environment health and configuration."""
    paths = default_paths()

    litellm_ok = False
    litellm_error: str | None = None
    try:
        import litellm  # noqa: F401

        litellm_ok = True
    except Exception as exc:
        litellm_error = str(exc)

    data = {
        "schema_version": "1",
        "package_version": __version__,
        "python_version": sys.version,
        "platform": platform.platform(),
        "litellm_available": litellm_ok,
        "litellm_error": litellm_error,
        "paths": {
            "config_dir": str(paths.config_dir),
            "data_dir": str(paths.data_dir),
            "cache_dir": str(paths.cache_dir),
        },
    }

    if output_format == OutputFormat.json:
        # Use print() to avoid Rich markup processing corrupting JSON output.
        print(json.dumps(data, indent=2))
    else:
        table = Table(title="model-compass doctor", show_header=True)
        table.add_column("Check", style="bold")
        table.add_column("Value")

        table.add_row("Package version", __version__)
        table.add_row("Python version", sys.version.split()[0])
        table.add_row("Platform", platform.platform())
        table.add_row("LiteLLM available", "✓" if litellm_ok else f"✗  {litellm_error}")
        table.add_row("Config dir", str(paths.config_dir))
        table.add_row("Data dir", str(paths.data_dir))
        table.add_row("Cache dir", str(paths.cache_dir))

        console.print(table)


@app.command()
def models(
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format: table or json")
    ] = OutputFormat.table,
    offline: Annotated[bool, typer.Option(help="Use the cached OpenRouter catalog only")] = False,
) -> None:
    """List normalized OpenRouter models."""
    try:
        snapshot = analytics.catalog.refresh(offline=offline, include_litellm=False)
    except ModelCompassError as exc:
        err_console.print(f"Unable to load catalog: {exc}")
        raise typer.Exit(code=1) from exc

    profiles = [snapshot.models[key] for key in sorted(snapshot.models)]
    rows = [
        {
            "id": profile.identity.canonical_id,
            "name": profile.identity.display_name,
            "context_length": profile.capabilities.context_length,
            "pricing": {
                key: str(component.amount)
                for key, component in sorted(profile.pricing.components.items())
            },
        }
        for profile in profiles
    ]
    if output_format == OutputFormat.json:
        print(json.dumps({"schema_version": "1", "models": rows}, indent=2, sort_keys=True))
        return

    table = Table(title="Available models")
    table.add_column("Model", style="bold")
    table.add_column("Name")
    table.add_column("Context")
    table.add_column("Input price")
    for profile, row in zip(profiles, rows, strict=True):
        table.add_row(
            profile.identity.canonical_id,
            profile.identity.display_name or "",
            str(profile.capabilities.context_length or ""),
            row["pricing"].get("prompt", "unknown"),
        )
    console.print(table)


@app.command()
def estimate(
    model_id: Annotated[str, typer.Option("--model", help="Canonical or provider-local model ID")],
    input_tokens: Annotated[int, typer.Option("--input-tokens", min=0)],
    output_tokens: Annotated[int, typer.Option("--output-tokens", min=0)],
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format: table or json")
    ] = OutputFormat.table,
    offline: Annotated[bool, typer.Option(help="Use the cached OpenRouter catalog only")] = False,
) -> None:
    """Estimate request cost for one catalog model."""
    try:
        snapshot = analytics.catalog.refresh(offline=offline, include_litellm=False)
        profile = _find_profile(snapshot.models.values(), model_id)
        if profile is None:
            raise ValueError(f"model {model_id!r} was not found in the catalog")
        request = RequestProfile(
            estimated_input_tokens=input_tokens, expected_output_tokens=output_tokens
        )
        result = estimate_cost(profile, request)
    except (ModelCompassError, ValueError) as exc:
        err_console.print(f"Unable to estimate cost: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == OutputFormat.json:
        payload = result.model_dump(mode="json")
        payload["schema_version"] = "1"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    table = Table(title="Estimated request cost")
    table.add_column("Model", style="bold")
    table.add_column("Cost (USD)")
    table.add_column("Missing components")
    table.add_row(
        result.model_id,
        str(result.amount_usd) if result.amount_usd is not None else "unknown",
        ", ".join(result.missing_components),
    )
    console.print(table)


@app.command()
def select(
    task: Annotated[str, typer.Option(help="Task label for task-specific evidence")] = "general",
    input_tokens: Annotated[
        int | None, typer.Option("--input-tokens", min=0, help="Estimated prompt token count")
    ] = None,
    output_tokens: Annotated[
        int | None, typer.Option("--output-tokens", min=0, help="Expected completion token count")
    ] = None,
    max_cost: Annotated[
        str | None, typer.Option("--max-cost", help="Maximum estimated cost in USD")
    ] = None,
    min_quality: Annotated[
        str | None, typer.Option("--min-quality", help="Minimum task-specific quality (0 to 1)")
    ] = None,
    max_latency_ms: Annotated[
        int | None, typer.Option("--max-latency-ms", min=0, help="Maximum measured latency")
    ] = None,
    requires_tools: Annotated[bool, typer.Option(help="Require tool/function calling")] = False,
    requires_structured_output: Annotated[
        bool, typer.Option(help="Require structured output")
    ] = False,
    policy: Annotated[SelectionPolicy, typer.Option(help="Ranking policy")] = SelectionPolicy.BEST,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format: table or json")
    ] = OutputFormat.table,
    offline: Annotated[bool, typer.Option(help="Use the cached OpenRouter catalog only")] = False,
) -> None:
    """Choose an eligible model using explicit request constraints."""
    try:
        request = RequestProfile(
            task=task,
            estimated_input_tokens=input_tokens,
            expected_output_tokens=output_tokens,
            max_cost_usd=_parse_decimal_option(max_cost, "--max-cost"),
            min_quality=_parse_decimal_option(min_quality, "--min-quality"),
            max_latency_ms=max_latency_ms,
            requires_tools=requires_tools,
            requires_structured_output=requires_structured_output,
        )
        snapshot = analytics.catalog.refresh(offline=offline, include_litellm=False)
        result = analytics.select(
            [snapshot.models[key] for key in sorted(snapshot.models)],
            request,
            policy=policy,
        )
    except (ModelCompassError, ValueError) as exc:
        err_console.print(f"Unable to select a model: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == OutputFormat.json:
        payload = result.model_dump(mode="json")
        payload["schema_version"] = "1"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return

    table = Table(title=f"Model selection ({policy.value})")
    table.add_column("Model", style="bold")
    table.add_column("Eligible")
    table.add_column("Quality")
    table.add_column("Cost (USD)")
    table.add_column("Reasons")
    for assessment in result.assessments:
        table.add_row(
            assessment.model_id,
            "yes" if assessment.eligible else "no",
            str(assessment.quality) if assessment.quality is not None else "unknown",
            str(assessment.expected_cost_usd)
            if assessment.expected_cost_usd is not None
            else "unknown",
            "; ".join(assessment.reasons),
        )
    console.print(table)


@app.command()
def pareto(
    objectives: Annotated[
        str,
        typer.Option(help="Comma-separated objectives: quality,reliability,cost,latency"),
    ] = "quality,cost",
    task: Annotated[str, typer.Option(help="Task label for task-specific evidence")] = "general",
    input_tokens: Annotated[int | None, typer.Option("--input-tokens", min=0)] = None,
    output_tokens: Annotated[int | None, typer.Option("--output-tokens", min=0)] = None,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format: table or json")
    ] = OutputFormat.table,
    offline: Annotated[bool, typer.Option(help="Use the cached OpenRouter catalog only")] = False,
) -> None:
    """Report the non-dominated eligible models for selected objectives."""
    try:
        selected_objectives = tuple(
            ParetoObjective(item.strip()) for item in objectives.split(",") if item.strip()
        )
        snapshot = analytics.catalog.refresh(offline=offline, include_litellm=False)
        request = RequestProfile(
            task=task,
            estimated_input_tokens=input_tokens,
            expected_output_tokens=output_tokens,
        )
        result = analytics.select(
            [snapshot.models[key] for key in sorted(snapshot.models)], request
        )
        frontier = pareto_frontier(result.assessments, selected_objectives)
    except (ModelCompassError, ValueError) as exc:
        err_console.print(f"Unable to calculate Pareto frontier: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == OutputFormat.json:
        print(
            json.dumps(
                {
                    "schema_version": "1",
                    "objectives": [item.value for item in selected_objectives],
                    "models": [item.model_dump(mode="json") for item in frontier],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return
    table = Table(title="Pareto frontier")
    table.add_column("Model", style="bold")
    table.add_column("Quality")
    table.add_column("Reliability")
    table.add_column("Cost (USD)")
    table.add_column("Latency (ms)")
    for item in frontier:
        table.add_row(
            item.model_id,
            str(item.quality) if item.quality is not None else "unknown",
            str(item.reliability) if item.reliability is not None else "unknown",
            str(item.expected_cost_usd) if item.expected_cost_usd is not None else "unknown",
            str(item.latency_ms) if item.latency_ms is not None else "unknown",
        )
    console.print(table)


@app.command()
def benchmark(
    dataset: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    outputs: Annotated[Path, typer.Option(exists=True, dir_okay=False, readable=True)],
    model_id: Annotated[str, typer.Option("--model", help="Model identifier for the report")],
    record: Annotated[
        bool,
        typer.Option(help="Store quality evidence locally for selection"),
    ] = False,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format: table or json")
    ] = OutputFormat.table,
) -> None:
    """Evaluate saved benchmark outputs offline with a deterministic evaluator."""
    try:
        dataset_model = BenchmarkDataset.model_validate_json(dataset.read_text(encoding="utf-8"))
        raw_outputs = json.loads(outputs.read_text(encoding="utf-8"))
        if not isinstance(raw_outputs, dict) or not all(
            isinstance(key, str) and isinstance(value, str) for key, value in raw_outputs.items()
        ):
            raise ValueError(
                "outputs file must contain a JSON object of string case IDs to strings"
            )
        report = evaluate_benchmark(dataset_model, raw_outputs, model_id=model_id)
        if record:
            analytics.record_benchmark(report)
    except (ModelCompassError, OSError, ValueError) as exc:
        err_console.print(f"Unable to evaluate benchmark: {exc}")
        raise typer.Exit(code=1) from exc

    if output_format == OutputFormat.json:
        payload = report.model_dump(mode="json")
        payload["schema_version"] = "1"
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    table = Table(title=f"Benchmark: {report.dataset} ({report.task})")
    table.add_column("Model", style="bold")
    table.add_column("Score")
    table.add_column("Samples")
    table.add_column("Passed")
    table.add_row(
        report.model_id,
        str(report.quality_score),
        str(report.sample_size),
        str(report.passed),
    )
    console.print(table)


@app.command()
def run(
    model_id: Annotated[str, typer.Option("--model", help="LiteLLM model identifier")],
    task: Annotated[str, typer.Option(help="Task label for recorded observations")] = "general",
) -> None:
    """Execute one prompt read from stdin and record aggregate usage."""
    prompt = sys.stdin.read()
    if not prompt:
        err_console.print("Provide a prompt on stdin.")
        raise typer.Exit(code=2)
    request = CompletionRequest(
        model_id=model_id,
        task=task,
        messages=[{"role": "user", "content": prompt}],
    )
    try:
        result = asyncio.run(analytics.execute(request))
    except ModelCompassError as exc:
        err_console.print(f"Execution failed: {exc}")
        raise typer.Exit(code=1) from exc
    print(result.output_text)


@app.command()
def observations(
    task: Annotated[str | None, typer.Option(help="Filter by exact task label")] = None,
    model_id: Annotated[
        str | None, typer.Option("--model", help="Filter by canonical model ID")
    ] = None,
    output_format: Annotated[
        OutputFormat, typer.Option("--format", help="Output format: table or json")
    ] = OutputFormat.table,
) -> None:
    """List locally recorded aggregate execution observations."""
    try:
        records = analytics.list_observations(model_id=model_id, task=task)
    except ModelCompassError as exc:
        err_console.print(f"Unable to read observations: {exc}")
        raise typer.Exit(code=1) from exc
    if output_format == OutputFormat.json:
        print(
            json.dumps(
                {
                    "schema_version": "1",
                    "observations": [item.model_dump(mode="json") for item in records],
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    table = Table(title="Execution observations")
    table.add_column("Model", style="bold")
    table.add_column("Task")
    table.add_column("Success")
    table.add_column("Latency (ms)")
    table.add_column("Cost (USD)")
    for item in records:
        table.add_row(
            item.model_id,
            item.task,
            "yes" if item.succeeded else "no",
            str(item.latency_ms),
            str(item.actual_cost_usd) if item.actual_cost_usd is not None else "unknown",
        )
    console.print(table)


def _parse_decimal_option(value: str | None, option_name: str) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(value)
    except InvalidOperation as exc:
        raise ValueError(f"{option_name} must be a decimal number") from exc


def _find_profile(profiles: Iterable[ModelProfile], requested_id: str) -> ModelProfile | None:
    lowered = requested_id.strip().lower()
    for profile in profiles:
        if (
            profile.identity.canonical_id.lower() == lowered
            or profile.identity.model_id.lower() == lowered
        ):
            return profile
    return None
