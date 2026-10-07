from __future__ import annotations

import importlib
import json
import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from typer.testing import CliRunner

from model_compass.benchmarks import BenchmarkRunOutcome
from model_compass.cli.app import app
from model_compass.domain import (
    BenchmarkResult,
    BenchmarkRun,
    CatalogSnapshot,
    CatalogSource,
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    Observation,
    PriceComponent,
    Pricing,
    QualityEvidence,
)
from model_compass.selection.engine import CandidateAssessment
from model_compass.storage import SQLiteObservationStore

runner = CliRunner()
cli_module = importlib.import_module("model_compass.cli.app")


def _profile(
    model_id: str = "small",
    *,
    prompt_price: str = "0.000001",
    completion_price: str = "0.000002",
    context_length: int = 1000,
) -> ModelProfile:
    """Build a fixed, text-capable catalog profile for CLI tests."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ModelProfile(
        identity=ModelIdentity(
            provider="test",
            model_id=model_id,
            canonical_id=f"test:{model_id}",
            display_name=model_id.title(),
        ),
        capabilities=ModelCapabilities(
            context_length=context_length,
            input_modalities=("text",),
            output_modalities=("text",),
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal(prompt_price)),
                "completion": PriceComponent(key="completion", amount=Decimal(completion_price)),
            }
        ),
        sources=(CatalogSource(name="test", retrieved_at=now),),
        retrieved_at=now,
    )


def _install_catalog(monkeypatch: pytest.MonkeyPatch, *profiles: ModelProfile):
    """Install a static catalog snapshot for CLI command tests."""
    first = profiles[0]
    snapshot = CatalogSnapshot(
        models={profile.identity.canonical_id: profile for profile in profiles},
        sources=first.sources,
        retrieved_at=first.retrieved_at,
    )
    monkeypatch.setattr(
        cli_module, "analytics", SimpleNamespace(catalog=SimpleNamespace(refresh=lambda **kwargs: snapshot))
    )


@pytest.mark.unit
def test_help_exposes_requested_groups_and_commands():
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
def test_catalog_model_estimate_and_compare_json(monkeypatch: pytest.MonkeyPatch):
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
            "--input-modality",
            "text",
            "--minimum-context",
            "500",
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
    missing = runner.invoke(app, ["models", "show", "not-a-model", "--offline"])
    assert missing.exit_code == 2


@pytest.mark.unit
def test_observation_benchmark_and_database_groups_use_configured_database(tmp_path: Path):
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
):
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


@pytest.mark.unit
def test_config_never_prints_credential_values_and_live_benchmark_requires_acknowledgement(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """[Unit] Keep credentials hidden and require explicit live benchmark consent.

    Scenario: Show config with a fake API key and attempt a benchmark without acknowledgement.
    Boundaries: No provider calls or network access are made.
    On failure, first check: environment key handling and the live-run guard.
    """
    secret = "test-secret-value"
    monkeypatch.setenv("OPENAI_API_KEY", secret)
    config = runner.invoke(app, ["config", "show", "--format", "json"])
    assert config.exit_code == 0
    assert secret not in config.output
    assert "OPENAI_API_KEY" in config.output

    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"record_type":"dataset","name":"tiny","version":"1"}\n'
        '{"record_type":"case","case_id":"one","task":"qa","input_text":"q",'
        '"evaluator":"exact","expected_output":"a"}\n',
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        ["benchmark", "run", "--dataset", str(dataset), "--model", "test:small"],
    )
    assert result.exit_code == 2
    assert "acknowledge-live" in result.output


@pytest.mark.unit
def test_doctor_uses_path_overrides_and_vacuum_maps_sqlite_errors(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """[Unit] Report configured paths and normalize SQLite vacuum failures.

    Scenario: Pass path overrides to doctor and simulate a locked database during vacuum.
    Boundaries: No provider requests; SQLite failure is raised by a patched store method.
    On failure, first check: root path propagation and storage exit-code mapping.
    """
    data_dir = tmp_path / "data"
    cache_dir = tmp_path / "cache"
    database = tmp_path / "observations.sqlite3"
    doctor = runner.invoke(
        app,
        [
            "--data-dir",
            str(data_dir),
            "--cache-dir",
            str(cache_dir),
            "--db",
            str(database),
            "doctor",
            "--format",
            "json",
        ],
    )
    assert doctor.exit_code == 0
    doctor_payload = json.loads(doctor.output)
    assert doctor_payload["paths"]["data_dir"] == str(data_dir)
    assert doctor_payload["paths"]["cache_dir"] == str(cache_dir)
    assert doctor_payload["database_path"] == str(database)

    def fail_vacuum(self: SQLiteObservationStore):
        """Raise the same SQLite error emitted for a locked database."""
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(SQLiteObservationStore, "vacuum", fail_vacuum)
    vacuum = runner.invoke(app, ["--db", str(database), "db", "vacuum"])
    assert vacuum.exit_code == 6
    assert "database is locked" in vacuum.output


@pytest.mark.unit
def test_compare_sorts_by_selected_policy_before_limit(monkeypatch: pytest.MonkeyPatch):
    """[Unit] Apply comparison limits after policy ranking with deterministic fallback.

    Scenario: The lexically last ranked model has the lowest cost, with an unranked candidate as fallback.
    Boundaries: Catalog access is replaced with local model profiles.
    On failure, first check: policy ranks order candidates before limiting and IDs break rankless ties.
    """
    _install_catalog(
        monkeypatch,
        _profile("a-unranked").model_copy(update={"pricing": Pricing(components={})}),
        _profile("a-expensive", prompt_price="0.00001"),
        _profile("z-cheap", prompt_price="0.000001"),
    )

    result = runner.invoke(
        app,
        ["compare", "--sort", "cheapest", "--limit", "1", "--input-tokens", "100", "--format", "json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["candidates"][0]["model"]["identity"]["canonical_id"] == "test:z-cheap"
    assert payload["candidates"][0]["rank_by_policy"]["cheapest"] == 1

    all_candidates = runner.invoke(
        app,
        ["compare", "--sort", "cheapest", "--limit", "3", "--input-tokens", "100", "--format", "json"],
    )
    assert all_candidates.exit_code == 0, all_candidates.output
    candidates = json.loads(all_candidates.output)["candidates"]
    assert [item["model"]["identity"]["canonical_id"] for item in candidates] == [
        "test:z-cheap",
        "test:a-expensive",
        "test:a-unranked",
    ]
    assert candidates[0]["rank_by_policy"]["cheapest"] == 1
    assert "cheapest" not in candidates[-1]["rank_by_policy"]


@pytest.mark.unit
def test_compare_uses_task_filtered_stored_observation_and_quality_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """[Unit] Use stored task evidence for comparison constraints and output.

    Scenario: Persist quality and latency observations for the requested task, then compare with thresholds.
    Boundaries: Catalog data and SQLite use temporary local fixtures; no provider or network calls occur.
    On failure, first check: compare passes task-filtered store evidence to compare_models.
    """
    profile = _profile()
    _install_catalog(monkeypatch, profile)
    database = tmp_path / "comparison.sqlite3"
    store = SQLiteObservationStore(database)
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_observations(
        [
            Observation(
                timestamp=now,
                model_id="test:small",
                task="qa",
                success=True,
                latency_ms=Decimal(100 + index * 20),
            )
            for index in range(5)
        ]
    )
    store.record_quality_evidence(
        QualityEvidence(
            model_id="test:small",
            task="qa",
            score=Decimal("0.9"),
            evaluator="exact",
            source="test",
            sample_count=5,
            observed_at=now,
        )
    )
    snapshot = cli_module.analytics.catalog.refresh()
    monkeypatch.setattr(
        cli_module,
        "CatalogService",
        lambda **kwargs: SimpleNamespace(refresh=lambda **refresh_kwargs: snapshot),
    )

    result = runner.invoke(
        app,
        [
            "--db",
            str(database),
            "compare",
            "--task",
            "qa",
            "--min-quality",
            "0.8",
            "--max-latency-ms",
            "200",
            "--min-reliability",
            "0.9",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    candidate = json.loads(result.output)["candidates"][0]
    assert candidate["eligibility"]["eligible"] is True
    assert candidate["quality_evidence"]["value"] == "0.9"
    assert candidate["latency_evidence"]["value"] == "180"
    assert candidate["reliability_evidence"]["value"] == "1"


@pytest.mark.unit
def test_pareto_include_dominated_excludes_ineligible_models(monkeypatch: pytest.MonkeyPatch):
    """[Unit] Keep ineligible assessments out of Pareto's dominated-model output.

    Scenario: Pareto analysis receives one eligible and one ineligible assessment.
    Boundaries: Catalog and selection are deterministic local fakes.
    On failure, first check: include-dominated filters assessments by eligibility.
    """
    eligible = CandidateAssessment(model_id="test:eligible", eligible=True, expected_cost_usd=Decimal("1"))
    ineligible = CandidateAssessment(model_id="test:ineligible", eligible=False, reasons=("rejected",))
    _install_catalog(monkeypatch, _profile("eligible"), _profile("ineligible"))
    catalog = cli_module.analytics.catalog
    monkeypatch.setattr(
        cli_module,
        "analytics",
        SimpleNamespace(
            catalog=catalog, select=lambda *args, **kwargs: SimpleNamespace(assessments=(eligible, ineligible))
        ),
    )
    monkeypatch.setattr(
        cli_module,
        "pareto_analysis",
        lambda *args, **kwargs: SimpleNamespace(frontier=(eligible,), dominated_by={}),
    )

    result = runner.invoke(app, ["pareto", "--include-dominated", "--format", "json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert [item["model_id"] for item in payload["models"]] == ["test:eligible"]


def _benchmark_fixture(tmp_path: Path, repetitions: int) -> tuple[Path, BenchmarkRunOutcome]:
    """Create a minimal dataset and repeat-indexed outcome for CLI persistence tests."""
    dataset = tmp_path / "dataset.jsonl"
    dataset.write_text(
        '{"record_type":"dataset","name":"tiny","version":"1"}\n'
        '{"record_type":"case","case_id":"one","task":"qa","input_text":"q",'
        '"evaluator":"exact","expected_output":"a"}\n',
        encoding="utf-8",
    )
    now = datetime(2026, 1, 1, tzinfo=UTC)
    run = BenchmarkRun(run_id="repeat-run", dataset_id="tiny", started_at=now, status="completed")
    results = tuple(
        BenchmarkResult(
            run_id=run.run_id,
            case_id="one",
            model_id="test:small",
            score=Decimal(repetition) / Decimal(max(repetitions - 1, 1)),
            cost=Decimal("0.2"),
            latency_ms=Decimal(100 + repetition * 100),
            metadata={"repetition": repetition},
        )
        for repetition in range(repetitions)
    )
    return dataset, BenchmarkRunOutcome(run=run, results=results, scored_cases=())


@pytest.mark.unit
def test_benchmark_repetitions_are_aggregated_before_storage(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """[Unit] Persist repeated benchmark outcomes without duplicate identities.

    Scenario: A fake live-run result contains two repetitions of the same case and model.
    Boundaries: Provider execution is replaced by a fixed outcome and SQLite is temporary.
    On failure, first check: persistence aggregates one identity and retains each repetition as metadata.
    """
    dataset, outcome = _benchmark_fixture(tmp_path, 2)

    async def fake_run(*args: Any, **kwargs: Any) -> BenchmarkRunOutcome:
        """Return the predetermined benchmark outcome."""
        return outcome

    monkeypatch.setattr(cli_module, "run_benchmark", fake_run)
    database = tmp_path / "benchmark.sqlite3"
    result = runner.invoke(
        app,
        [
            "--db",
            str(database),
            "benchmark",
            "run",
            "--dataset",
            str(dataset),
            "--model",
            "test:small",
            "--repetitions",
            "2",
            "--acknowledge-live",
            "--format",
            "json",
        ],
    )

    assert result.exit_code == 0, result.output
    stored = SQLiteObservationStore(database).query_benchmark_results(run_id=outcome.run.run_id)
    assert len(stored) == 1
    assert stored[0].score == Decimal("0.5")
    assert stored[0].latency_ms == Decimal("150")
    assert stored[0].metadata["repetition_count"] == 2
    assert [item["metadata"]["repetition"] for item in stored[0].metadata["repetitions"]] == [0, 1]


@pytest.mark.unit
def test_benchmark_invalid_max_cost_uses_cli_exit_code(tmp_path: Path):
    """[Unit] Classify malformed benchmark budget input as a CLI error.

    Scenario: Invoke a live benchmark with acknowledgement but a non-decimal maximum cost.
    Boundaries: The dataset is local and provider execution should not begin.
    On failure, first check: max-cost parsing happens before the benchmark execution handler.
    """
    dataset, _ = _benchmark_fixture(tmp_path, 1)
    result = runner.invoke(
        app,
        [
            "benchmark",
            "run",
            "--dataset",
            str(dataset),
            "--model",
            "test:small",
            "--max-cost",
            "not-money",
            "--acknowledge-live",
        ],
    )

    assert result.exit_code == 2
    assert "--max-cost must be a decimal number" in result.output


@pytest.mark.unit
def test_benchmark_sqlite_errors_use_storage_exit_code(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """[Unit] Map raw SQLite failures from benchmark persistence to storage exit code.

    Scenario: A live-run fixture succeeds but writing its benchmark result raises a SQLite lock error.
    Boundaries: The benchmark runner is replaced; only the local SQLite persistence call is patched.
    On failure, first check: raw sqlite3.Error is normalized to stable storage exit code 6.
    """
    dataset, outcome = _benchmark_fixture(tmp_path, 1)

    async def fake_run(*args: Any, **kwargs: Any) -> BenchmarkRunOutcome:
        """Return the predetermined benchmark outcome."""
        return outcome

    def fail_record(self: SQLiteObservationStore, result: BenchmarkResult):
        """Simulate a raw SQLite lock error during result persistence."""
        raise sqlite3.OperationalError("database is locked")

    monkeypatch.setattr(cli_module, "run_benchmark", fake_run)
    monkeypatch.setattr(SQLiteObservationStore, "record_benchmark_result", fail_record)
    result = runner.invoke(
        app,
        [
            "--db",
            str(tmp_path / "locked.sqlite3"),
            "benchmark",
            "run",
            "--dataset",
            str(dataset),
            "--model",
            "test:small",
            "--acknowledge-live",
        ],
    )

    assert result.exit_code == 6
    assert "database is locked" in result.output
