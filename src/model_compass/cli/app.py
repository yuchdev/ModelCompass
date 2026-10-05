"""CLI entry points for model-compass."""

from __future__ import annotations

import json
import platform
import sys
from enum import StrEnum
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from model_compass import __version__
from model_compass.config import default_paths

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
