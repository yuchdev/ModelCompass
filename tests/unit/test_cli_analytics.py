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
    CatalogSnapshot,
    CatalogSource,
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
)
from model_compass.exceptions import ModelCompassError
from model_compass.execution import CompletionRequest, ExecutionResult
from model_compass.metrics import Observation
from model_compass.selection import (
    CandidateAssessment,
    SelectionPolicy,
    SelectionResult,
    select_model,
)

runner = CliRunner()
cli_app_module = importlib.import_module("model_compass.cli.app")


def _profile() -> ModelProfile:
    """Build a small text-capable model profile fixture used across the CLI tests."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id="small", canonical_id="test:small", display_name="Small"),
        capabilities=ModelCapabilities(context_length=1000, input_modalities=("text",), output_modalities=("text",)),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal("0.000001")),
                "completion": PriceComponent(key="completion", amount=Decimal("0.000002")),
            }
        ),
        retrieved_at=now,
    )


@pytest.mark.unit
def test_models_json_lists_decimal_pricing_without_rich_markup(
    monkeypatch: pytest.MonkeyPatch,
):
    """[E2E] Models json lists decimal pricing without rich markup: verifies the described behaviour holds.

    Scenario: Exercises models json lists decimal pricing without rich markup and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()
    snapshot = CatalogSnapshot(
        models={profile.identity.canonical_id: profile},
        sources=(CatalogSource(name="test", retrieved_at=datetime(2026, 1, 1, tzinfo=UTC)),),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    fake = SimpleNamespace(catalog=SimpleNamespace(refresh=lambda **kwargs: snapshot))
    monkeypatch.setattr(cli_app_module, "analytics", fake)

    result = runner.invoke(app, ["models", "--format", "json", "--offline"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["schema_version"] == "1"
    assert payload["models"][0]["pricing"]["prompt"] == "0.000001"
    assert "\x1b[" not in result.output


@pytest.mark.unit
def test_select_table_and_catalog_error(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Select table and catalog error: verifies the described behaviour holds.

    Scenario: Exercises select table and catalog error and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()
    fake = SimpleNamespace(
        catalog=SimpleNamespace(refresh=lambda **kwargs: SimpleNamespace(models={"test:small": profile})),
        select=lambda profiles, request, *, policy: select_model(profiles, request, policy=policy),
    )
    monkeypatch.setattr(cli_app_module, "analytics", fake)
    result = runner.invoke(app, ["select"])
    assert result.exit_code == 0
    assert "Model selection" in result.output

    def fail(**kwargs: object):
        """Raise a catalog error to simulate an offline refresh failure."""
        raise ModelCompassError("offline catalog missing")

    monkeypatch.setattr(
        cli_app_module,
        "analytics",
        SimpleNamespace(catalog=SimpleNamespace(refresh=fail)),
    )
    failed = runner.invoke(app, ["select"])
    assert failed.exit_code == 1
    assert "Unable to select a model" in failed.output


@pytest.mark.unit
def test_models_table_and_catalog_error(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Models table and catalog error: verifies the described behaviour holds.

    Scenario: Exercises models table and catalog error and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()
    snapshot = SimpleNamespace(models={"test:small": profile})
    fake = SimpleNamespace(catalog=SimpleNamespace(refresh=lambda **kwargs: snapshot))
    monkeypatch.setattr(cli_app_module, "analytics", fake)
    table = runner.invoke(app, ["models"])
    assert table.exit_code == 0
    assert "Available models" in table.output

    def fail(**kwargs: object):
        """Raise a catalog error to simulate an unavailable catalog refresh."""
        raise ModelCompassError("catalog unavailable")

    monkeypatch.setattr(cli_app_module, "analytics", SimpleNamespace(catalog=SimpleNamespace(refresh=fail)))
    failed = runner.invoke(app, ["models"])
    assert failed.exit_code == 1
    assert "Unable to load catalog: catalog unavailable" in failed.output


@pytest.mark.unit
def test_select_json_returns_explanation_and_policy(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Select json returns explanation and policy: verifies the described behaviour holds.

    Scenario: Exercises select json returns explanation and policy and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()

    class FakeAnalytics:
        """Analytics facade double exposing a static catalog and real selection."""

        catalog = SimpleNamespace(refresh=lambda **kwargs: SimpleNamespace(models={"test:small": profile}))

        @staticmethod
        def select(
            profiles: list[ModelProfile],
            request: RequestProfile,
            *,
            policy: SelectionPolicy,
        ) -> SelectionResult:
            """Delegate to the real select_model with the given policy."""
            return select_model(profiles, request, policy=policy)

    monkeypatch.setattr(cli_app_module, "analytics", FakeAnalytics())
    result = runner.invoke(
        app,
        [
            "select",
            "--format",
            "json",
            "--input-tokens",
            "10",
            "--output-tokens",
            "10",
            "--max-cost",
            "0.001",
            "--policy",
            "cheapest",
        ],
    )
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["policy"] == "cheapest"
    assert payload["selected"]["model_id"] == "test:small"
    assert payload["schema_version"] == "1"


@pytest.mark.unit
def test_observations_cli_json(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Observations cli json: verifies the described behaviour holds.

    Scenario: Exercises observations cli json and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    item = Observation(
        model_id="test:small",
        task="general",
        succeeded=True,
        latency_ms=9,
        actual_cost_usd=Decimal("0.01"),
    )
    fake = SimpleNamespace(list_observations=lambda **kwargs: [item])
    monkeypatch.setattr(cli_app_module, "analytics", fake)

    result = runner.invoke(app, ["observations", "--format", "json", "--task", "general"])
    assert result.exit_code == 0
    assert json.loads(result.output)["observations"][0]["actual_cost_usd"] == "0.01"

    table = runner.invoke(app, ["observations"])
    assert table.exit_code == 0
    assert "Execution observations" in table.output

    def fail(**kwargs: object) -> list[Observation]:
        """Raise a catalog error to simulate an unavailable observation store."""
        raise ModelCompassError("database unavailable")

    monkeypatch.setattr(cli_app_module, "analytics", SimpleNamespace(list_observations=fail))
    failed = runner.invoke(app, ["observations"])
    assert failed.exit_code == 1
    assert "Unable to read observations" in failed.output


@pytest.mark.unit
def test_estimate_cli_json(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Estimate cli json: verifies the described behaviour holds.

    Scenario: Exercises estimate cli json and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()
    snapshot = SimpleNamespace(models={"test:small": profile})
    monkeypatch.setattr(
        cli_app_module,
        "analytics",
        SimpleNamespace(catalog=SimpleNamespace(refresh=lambda **kwargs: snapshot)),
    )
    result = runner.invoke(
        app,
        [
            "estimate",
            "--model",
            "test:small",
            "--input-tokens",
            "10",
            "--output-tokens",
            "10",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    assert json.loads(result.output)["amount_usd"] == "0.000030"


@pytest.mark.unit
def test_estimate_table_and_missing_model(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Estimate table and missing model: verifies the described behaviour holds.

    Scenario: Exercises estimate table and missing model and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()
    snapshot = SimpleNamespace(models={"test:small": profile})
    monkeypatch.setattr(
        cli_app_module,
        "analytics",
        SimpleNamespace(catalog=SimpleNamespace(refresh=lambda **kwargs: snapshot)),
    )
    result = runner.invoke(
        app,
        ["estimate", "--model", "test:small", "--input-tokens", "1", "--output-tokens", "1"],
    )
    assert result.exit_code == 0
    assert "Estimated request cost" in result.output
    missing = runner.invoke(
        app,
        [
            "estimate",
            "--model",
            "absent",
            "--input-tokens",
            "1",
            "--output-tokens",
            "1",
        ],
    )
    assert missing.exit_code == 1
    assert "was not found" in missing.output


@pytest.mark.unit
def test_pareto_cli_json_reports_objectives(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Pareto cli json reports objectives: verifies the described behaviour holds.

    Scenario: Exercises pareto cli json reports objectives and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    candidate = CandidateAssessment(
        model_id="test:small",
        eligible=True,
        quality=Decimal("0.9"),
        expected_cost_usd=Decimal("0.01"),
    )
    fake = SimpleNamespace(
        catalog=SimpleNamespace(refresh=lambda **kwargs: SimpleNamespace(models={})),
        select=lambda *args, **kwargs: SimpleNamespace(assessments=(candidate,)),
    )
    monkeypatch.setattr(cli_app_module, "analytics", fake)
    result = runner.invoke(app, ["pareto", "--objectives", "quality,cost", "--format", "json"])
    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["objectives"] == ["quality", "cost"]
    assert payload["models"][0]["model_id"] == "test:small"


@pytest.mark.unit
def test_pareto_table_and_invalid_objective(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Pareto table and invalid objective: verifies the described behaviour holds.

    Scenario: Exercises pareto table and invalid objective and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    candidate = CandidateAssessment(
        model_id="test:small",
        eligible=True,
        quality=Decimal("0.9"),
        expected_cost_usd=Decimal("0.01"),
    )
    fake = SimpleNamespace(
        catalog=SimpleNamespace(refresh=lambda **kwargs: SimpleNamespace(models={})),
        select=lambda *args, **kwargs: SimpleNamespace(assessments=(candidate,)),
    )
    monkeypatch.setattr(cli_app_module, "analytics", fake)
    table = runner.invoke(app, ["pareto"])
    assert table.exit_code == 0
    assert "Pareto frontier" in table.output
    invalid = runner.invoke(app, ["pareto", "--objectives", "mystery"])
    assert invalid.exit_code == 1
    assert "Unable to calculate Pareto frontier" in invalid.output


@pytest.mark.unit
def test_benchmark_cli_evaluates_json_files(tmp_path: Path):
    """[E2E] Benchmark cli evaluates json files: verifies the described behaviour holds.

    Scenario: Exercises benchmark cli evaluates json files and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    dataset_file = tmp_path / "dataset.jsonl"
    output_file = tmp_path / "outputs.json"
    dataset_file.write_text(
        json.dumps({"record_type": "dataset", "name": "tiny", "version": "1.0.0"})
        + "\n"
        + json.dumps(
            {
                "record_type": "case",
                "case_id": "one",
                "task": "qa",
                "input_text": "question",
                "evaluator": "exact",
                "expected_output": "answer",
            }
        )
        + "\n",
        encoding="utf-8",
    )
    output_file.write_text(json.dumps({"one": "answer"}), encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--dataset",
            str(dataset_file),
            "--outputs",
            str(output_file),
            "--model",
            "test:small",
            "--format",
            "json",
        ],
    )
    assert result.exit_code == 0
    report = json.loads(result.output)
    assert report["quality_score"] == "1"
    assert report["sample_size"] == 1

    table = runner.invoke(
        app,
        [
            "benchmark",
            "--dataset",
            str(dataset_file),
            "--outputs",
            str(output_file),
            "--model",
            "test:small",
        ],
    )
    assert table.exit_code == 0
    assert "Benchmark: tiny" in table.output


@pytest.mark.unit
def test_benchmark_cli_can_persist_quality_evidence(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """[E2E] Benchmark cli can persist quality evidence: verifies the described behaviour holds.

    Scenario: Exercises benchmark cli can persist quality evidence and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    dataset_file = tmp_path / "dataset.jsonl"
    output_file = tmp_path / "outputs.json"
    dataset_file.write_text(
        '{"record_type":"dataset","name":"tiny","version":"1.0.0"}\n'
        '{"record_type":"case","case_id":"one","task":"qa","input_text":"q",'
        '"evaluator":"exact","expected_output":"a"}\n',
        encoding="utf-8",
    )
    output_file.write_text('{"one":"a"}', encoding="utf-8")
    records: list[object] = []
    monkeypatch.setattr(
        cli_app_module,
        "analytics",
        SimpleNamespace(record_benchmark=records.append),
    )
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--dataset",
            str(dataset_file),
            "--outputs",
            str(output_file),
            "--model",
            "test:small",
            "--record",
        ],
    )
    assert result.exit_code == 0
    assert len(records) == 1


@pytest.mark.unit
def test_benchmark_cli_rejects_invalid_output_file(tmp_path: Path):
    """[E2E] Benchmark cli rejects invalid output file: verifies the described behaviour holds.

    Scenario: Exercises benchmark cli rejects invalid output file and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    dataset_file = tmp_path / "dataset.jsonl"
    output_file = tmp_path / "outputs.json"
    dataset_file.write_text(
        '{"record_type":"dataset","name":"d","version":"1.0.0"}\n'
        '{"record_type":"case","case_id":"one","task":"t","input_text":"q",'
        '"evaluator":"exact","expected_output":"a"}\n',
        encoding="utf-8",
    )
    output_file.write_text('["not", "an object"]', encoding="utf-8")
    result = runner.invoke(
        app,
        [
            "benchmark",
            "--dataset",
            str(dataset_file),
            "--outputs",
            str(output_file),
            "--model",
            "test:small",
        ],
    )
    assert result.exit_code == 1
    assert "outputs file must contain" in result.output


@pytest.mark.unit
def test_run_cli_reads_prompt_from_stdin_without_rich_markup(
    monkeypatch: pytest.MonkeyPatch,
):
    """[E2E] Run cli reads prompt from stdin without rich markup: verifies the described behaviour holds.

    Scenario: Exercises run cli reads prompt from stdin without rich markup and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """

    class FakeAnalytics:
        """Analytics facade double whose execute returns a fixed completion result."""

        @staticmethod
        async def execute(request: CompletionRequest) -> ExecutionResult:
            """Assert the prompt was forwarded and return a canned result."""
            assert request.messages[0]["content"] == "private prompt"
            return ExecutionResult(
                model_id=request.model_id,
                task=request.task,
                output_text="[bold]literal output[/bold]",
                latency_ms=1,
            )

    monkeypatch.setattr(cli_app_module, "analytics", FakeAnalytics())
    result = runner.invoke(app, ["run", "--model", "test:model"], input="private prompt")
    assert result.exit_code == 0
    assert result.output == "[bold]literal output[/bold]\n"


@pytest.mark.unit
def test_run_cli_handles_missing_prompt_and_execution_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """[E2E] Run cli handles missing prompt and execution error: verifies the described behaviour holds.

    Scenario: Exercises run cli handles missing prompt and execution error and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    no_prompt = runner.invoke(app, ["run", "--model", "test:model"])
    assert no_prompt.exit_code == 2
    assert "Provide a prompt on stdin" in no_prompt.output

    class FailingAnalytics:
        """Analytics facade double whose execute always raises an execution error."""

        @staticmethod
        async def execute(request: CompletionRequest) -> ExecutionResult:
            """Raise a model error to simulate a provider failure during execution."""
            raise ModelCompassError("provider unavailable")

    monkeypatch.setattr(cli_app_module, "analytics", FailingAnalytics())
    failed = runner.invoke(app, ["run", "--model", "test:model"], input="prompt")
    assert failed.exit_code == 1
    assert "Execution failed" in failed.output


@pytest.mark.unit
def test_select_invalid_decimal_returns_actionable_error(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Select invalid decimal returns actionable error: verifies the described behaviour holds.

    Scenario: Exercises select invalid decimal returns actionable error and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    monkeypatch.setattr(cli_app_module, "analytics", SimpleNamespace())
    result = runner.invoke(app, ["select", "--max-cost", "not-money"])
    assert result.exit_code == 1
    assert "--max-cost must be a decimal number" in result.output


@pytest.mark.unit
def test_select_accepts_modality_and_context_options(monkeypatch: pytest.MonkeyPatch):
    """[E2E] Select accepts modality and context options: verifies the described behaviour holds.

    Scenario: Exercises select accepts modality and context options and asserts the expected outcome.
    Boundaries: Drives the real CLI through Typer's CliRunner; catalog, store, and backend collaborators are faked in-process.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = _profile()
    seen: list[RequestProfile] = []

    class FakeAnalytics:
        """Analytics facade double that records each request and runs real selection."""

        catalog = SimpleNamespace(refresh=lambda **kwargs: SimpleNamespace(models={"test:small": profile}))

        @staticmethod
        def select(
            profiles: list[ModelProfile], request: RequestProfile, *, policy: SelectionPolicy
        ) -> SelectionResult:
            """Capture the request and delegate to the real select_model."""
            seen.append(request)
            return select_model(profiles, request, policy=policy)

    monkeypatch.setattr(cli_app_module, "analytics", FakeAnalytics())
    result = runner.invoke(
        app,
        [
            "select",
            "--format",
            "json",
            "--input-modality",
            "text",
            "--output-modality",
            "text",
            "--minimum-context",
            "500",
        ],
    )
    assert result.exit_code == 0
    assert seen[0].input_modalities == frozenset({"text"})
    assert seen[0].output_modalities == frozenset({"text"})
    assert seen[0].minimum_context == 500

    rejected = runner.invoke(
        app,
        ["select", "--format", "json", "--input-modality", "image", "--minimum-context", "5000"],
    )
    assert rejected.exit_code == 0
    assert json.loads(rejected.output)["selected"] is None
