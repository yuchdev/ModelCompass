from __future__ import annotations

import importlib
import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import pytest
from typer.testing import CliRunner

from model_compass.cli.app import app
from model_compass.domain import (
    BenchmarkResult,
    BenchmarkRun,
    CatalogSnapshot,
    CatalogSource,
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
)
from model_compass.storage import SQLiteObservationStore

runner = CliRunner()
cli_module = importlib.import_module("model_compass.cli.app")


def _profile() -> ModelProfile:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ModelProfile(
        identity=ModelIdentity(
            provider="test",
            model_id="small",
            canonical_id="test:small",
            display_name="Small",
        ),
        capabilities=ModelCapabilities(
            context_length=1000,
            input_modalities=("text",),
            output_modalities=("text",),
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal("0.000001")),
                "completion": PriceComponent(key="completion", amount=Decimal("0.000002")),
            }
        ),
        sources=(CatalogSource(name="test", retrieved_at=now),),
        retrieved_at=now,
    )


@pytest.mark.unit
def test_help_exposes_requested_groups_and_commands() -> None:
    """[Unit] Verify generated help exposes the stable command tree.

    Scenario: Invoke root and group help through Typer's CliRunner.
    Boundaries: No network, database, provider, or external service access.
    On failure, first check: command registrations and Typer group callbacks.
    """
    help_result = runner.invoke(app, ["--help"])
    assert help_result.exit_code == 0
    for group in ("config", "catalog", "models", "observations", "benchmark", "db"):
        assert group in help_result.output

    for group, command in (
        ("config", "show"),
        ("catalog", "refresh"),
        ("models", "list"),
        ("observations", "stats"),
        ("benchmark", "run"),
        ("db", "vacuum"),
    ):
        result = runner.invoke(app, [group, command, "--help"])
        assert result.exit_code == 0


@pytest.mark.unit
def test_catalog_model_estimate_and_compare_json(monkeypatch: pytest.MonkeyPatch) -> None:
    """[Unit] Exercise catalog, models, estimate, and compare JSON without network.

    Scenario: Use one normalized fake catalog profile for CLI commands.
    Boundaries: Catalog calls are replaced by an in-memory snapshot.
    On failure, first check: request conversion and versioned JSON serialization.
    """
    profile = _profile()
    snapshot = CatalogSnapshot(
        models={profile.identity.canonical_id: profile},
        sources=profile.sources,
        retrieved_at=profile.retrieved_at,
    )
    fake = SimpleNamespace(catalog=SimpleNamespace(refresh=lambda **kwargs: snapshot))
    monkeypatch.setattr(cli_module, "analytics", fake)

    cases = (
        ["catalog", "refresh", "--source", "openrouter", "--format", "json"],
        ["catalog", "sources", "--format", "json"],
        ["catalog", "status", "--format", "json"],
        ["models", "list", "--offline", "--format", "json"],
        ["models", "show", "test:small", "--offline", "--format", "json"],
        [
            "estimate",
            "--model",
            "test:small",
            "--input-tokens",
            "10",
            "--expected-output-tokens",
            "10",
            "--format",
            "json",
        ],
        ["compare", "--input-tokens", "10", "--expected-output-tokens", "10", "--format", "json"],
    )
    for args in cases:
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output, result.exception)
        payload = json.loads(result.output)
        assert payload["schema_version"] == 1
        assert isinstance(payload["command"], str)

    estimate = runner.invoke(
        app,
        ["estimate", "--model", "test:small", "--prompt", "hello", "--format", "json"],
    )
    assert estimate.exit_code == 0
    assert json.loads(estimate.output)["estimates"][0]["input_tokens"] > 0


@pytest.mark.unit
def test_observation_benchmark_and_database_groups_use_configured_database(tmp_path: Path) -> None:
    """[Unit] Exercise local observation, benchmark, and database command groups.

    Scenario: Operate on a temporary SQLite store using only explicit file paths.
    Boundaries: No network or provider execution; benchmark records are fixed fixtures.
    On failure, first check: database path propagation and storage protocol calls.
    """
    db = tmp_path / "analytics.sqlite3"
    global_options = ["--db", str(db)]
    stats = runner.invoke(app, [*global_options, "observations", "stats", "--format", "json"])
    assert stats.exit_code == 0
    assert json.loads(stats.output)["sample_count"] == 0

    exported_path = tmp_path / "observations.jsonl"
    exported = runner.invoke(app, [*global_options, "observations", "export", "--output", str(exported_path)])
    assert exported.exit_code == 0
    imported = runner.invoke(app, [*global_options, "observations", "import", str(exported_path)])
    assert imported.exit_code == 0

    started = datetime(2026, 1, 1, tzinfo=UTC)
    store = SQLiteObservationStore(db)
    run = BenchmarkRun(run_id="test-run", dataset_id="tiny", started_at=started, status="completed")
    store.record_benchmark_run(run)
    store.record_benchmark_result(
        BenchmarkResult(
            run_id=run.run_id,
            case_id="case-1",
            model_id="test:small",
            score=Decimal("1"),
        )
    )

    for args in (
        [*global_options, "benchmark", "list", "--format", "json"],
        [*global_options, "benchmark", "show", "test-run", "--format", "json"],
        [
            *global_options,
            "benchmark",
            "export",
            "--run-id",
            "test-run",
            "--output",
            str(tmp_path / "run.json"),
        ],
        [*global_options, "db", "status", "--format", "json"],
        [*global_options, "db", "vacuum"],
    ):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output, result.exception)
    assert (
        json.loads(runner.invoke(app, [*global_options, "benchmark", "show", "test-run", "--format", "json"]).output)[
            "results"
        ][0]["score"]
        == "1"
    )


@pytest.mark.unit
def test_config_paths_do_not_create_directories_and_empty_selection_has_exit_code_3(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """[Unit] Verify path overrides remain lazy and selection uses stable no-match code.

    Scenario: Invoke config paths with fresh paths and select with an empty catalog.
    Boundaries: No network; paths are inspected but never created.
    On failure, first check: root option processing and centralized exit behavior.
    """
    data_dir = tmp_path / "new-data"
    cache_dir = tmp_path / "new-cache"
    result = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "--cache-dir",
            str(cache_dir),
            "config",
            "paths",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert not data_dir.exists()
    assert not cache_dir.exists()
    assert json.loads(result.output)["paths"]["data_dir"] == str(data_dir)

    monkeypatch.setattr(
        cli_module,
        "analytics",
        SimpleNamespace(
            catalog=SimpleNamespace(refresh=lambda **kwargs: SimpleNamespace(models={})),
            select=lambda *args, **kwargs: SimpleNamespace(
                selected=None,
                policy=SimpleNamespace(value="best"),
                assessments=(),
                ranked=(),
                human_summary=lambda: "No model was selected.",
            ),
        ),
    )
    empty = runner.invoke(app, ["select", "--format", "json"])
    assert empty.exit_code == 3
    assert json.loads(empty.output)["selected"] is None
