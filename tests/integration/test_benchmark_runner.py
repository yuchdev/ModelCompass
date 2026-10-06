from __future__ import annotations

import datetime as dt
import json
from decimal import Decimal
from pathlib import Path

import pytest

from model_compass.benchmarks import (
    BenchmarkCase,
    BenchmarkDataset,
    BenchmarkRunConfig,
    run_benchmark,
    summarize_quality,
)
from model_compass.domain import ModelIdentity, ModelProfile, build_request_profile, canonical_model_id
from model_compass.execution.backend import CompletionRequest, ExecutionError
from model_compass.selection.engine import SelectionDataPolicy, SelectionPolicy, select_model
from model_compass.storage import SQLiteObservationStore
from tests.fixtures.fake_execution_backend import FakeExecutionBackend


def _dataset() -> BenchmarkDataset:
    """Build a tiny two-case, single-task arithmetic dataset."""
    return BenchmarkDataset(
        name="arithmetic-smoke",
        version="1.0.0",
        cases=(
            BenchmarkCase(
                case_id="two-plus-two", task="qa", input_text="2+2=?", evaluator="exact", expected_output="4"
            ),
            BenchmarkCase(
                case_id="three-plus-three", task="qa", input_text="3+3=?", evaluator="exact", expected_output="6"
            ),
        ),
    )


def _profile(provider: str, model_id: str) -> ModelProfile:
    """Build a minimal, otherwise-empty model profile for selection."""
    identity = ModelIdentity(provider=provider, model_id=model_id, canonical_id=canonical_model_id(provider, model_id))
    return ModelProfile(identity=identity, retrieved_at=dt.datetime.now(dt.UTC))


_CORRECT_ANSWERS = {"2+2=?": "4", "3+3=?": "6"}


def _good_responder(request: CompletionRequest) -> str:
    """Answer each case correctly by looking up its prompt text."""
    return _CORRECT_ANSWERS[request.messages[-1]["content"]]


def _flaky_responder(request: CompletionRequest) -> str:
    """Answer the first case correctly but raise for the second, simulating a mid-run failure."""
    prompt = request.messages[-1]["content"]
    if prompt == "2+2=?":
        return "4"
    raise ExecutionError("simulated transient failure", latency_ms=1)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_benchmark_run_feeds_storage_and_selector_end_to_end(tmp_path: Path):
    """[Integration] end-to-end benchmark pipeline: fake backend -> SQLite -> quality -> selector.

    Scenario: Runs a tiny dataset against three models (one perfect, one wrong, one partially
        failing), persists the run and results to a temp SQLite store, aggregates quality,
        records it as evidence, and confirms select_model picks the best-quality model while
        the flaky model's completed case is still counted.
    Boundaries: Real BenchmarkDataset/run_benchmark/SQLiteObservationStore/select_model; the
        execution backend is a local fake, no network or external services.
    On failure, first check: run_benchmark's per-case isolation and the SQLite round trip.
    """
    dataset = _dataset()
    backend = FakeExecutionBackend(
        {
            "test:good": _good_responder,
            "test:bad": "wrong answer",
            "test:flaky": _flaky_responder,
        }
    )
    outcome = await run_benchmark(
        dataset,
        ["test:good", "test:bad", "test:flaky"],
        backend=backend,
        config=BenchmarkRunConfig(repetitions=1, concurrency=2),
    )

    assert len(outcome.results) == 6  # 3 models x 2 cases
    flaky_results = {result.case_id: result for result in outcome.results if result.model_id == "test:flaky"}
    assert flaky_results["two-plus-two"].score == Decimal(1)
    assert flaky_results["three-plus-three"].score is None
    assert flaky_results["three-plus-three"].metadata["error_category"] == "execution_error"

    store = SQLiteObservationStore(tmp_path / "bench.sqlite3")
    store.record_benchmark_run(outcome.run)
    for result in outcome.results:
        store.record_benchmark_result(result)

    stored_run = store.query_benchmark_runs()[0]
    assert stored_run.dataset_hash == dataset.content_hash
    stored_results = store.query_benchmark_results(run_id=outcome.run.run_id)
    assert len(stored_results) == 6

    summaries = summarize_quality(outcome.scored_cases, group_by="task", seed=1)
    for summary in summaries:
        store.record_quality_evidence(summary.to_quality_evidence())

    quality_evidence = store.list_quality_evidence(task="qa")
    assert len(quality_evidence) == 3

    profiles = [_profile("test", "good"), _profile("test", "bad"), _profile("test", "flaky")]
    request = build_request_profile(task="qa")
    lenient = SelectionDataPolicy(
        reject_missing_latency=False, reject_missing_reliability=False, reject_missing_cost=False
    )
    result = select_model(
        profiles, request, policy=SelectionPolicy.BEST, quality_evidence=quality_evidence, missing_data=lenient
    )

    assert result.selected is not None
    # "good" (2/2 correct) and "flaky" (1/1 completed correct) tie on quality and both
    # outrank "bad" (0/2 correct); the flaky model's one completed case is still counted
    # rather than being dropped or treated as a failure.
    assert result.selected.model_id in {"test:good", "test:flaky"}
    by_model = {item.model_id: item for item in result.assessments}
    assert by_model["test:good"].quality == Decimal(1)
    assert by_model["test:flaky"].quality == Decimal(1)
    assert by_model["test:bad"].quality == Decimal(0)


@pytest.mark.integration
@pytest.mark.asyncio
async def test_benchmark_run_jsonl_export_round_trips_through_storage(tmp_path: Path):
    """[Integration] JSONL export/import: a run's results survive an export/import round trip.

    Scenario: Runs a dataset, persists results to one store, exports JSONL, and imports it
        into a second, empty store.
    Boundaries: Real run_benchmark and SQLiteObservationStore; the execution backend is a
        local fake, no network.
    On failure, first check: SQLiteObservationStore.export_jsonl/import_jsonl field round-tripping
        for benchmark_result records.
    """
    dataset = _dataset()
    backend = FakeExecutionBackend({"test:good": _good_responder})
    outcome = await run_benchmark(dataset, ["test:good"], backend=backend)

    source_store = SQLiteObservationStore(tmp_path / "source.sqlite3")
    for result in outcome.results:
        source_store.record_benchmark_result(result)

    exported = source_store.export_jsonl()
    lines = [json.loads(line) for line in exported.splitlines()]
    assert all(line["record_type"] == "benchmark_result" for line in lines)
    assert {line["record"]["case_id"] for line in lines} == {"two-plus-two", "three-plus-three"}

    destination_store = SQLiteObservationStore(tmp_path / "destination.sqlite3")
    imported_count = destination_store.import_jsonl(exported)
    assert imported_count == len(outcome.results)
    assert len(destination_store.query_benchmark_results()) == len(outcome.results)
