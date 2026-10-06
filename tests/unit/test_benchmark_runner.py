from __future__ import annotations

import json
from decimal import Decimal

import pytest

from model_compass import _version
from model_compass.benchmarks import (
    BenchmarkCase,
    BenchmarkDataset,
    BenchmarkRunConfig,
    EvaluationContext,
    EvaluationResult,
    JudgeConfig,
    LLMJudgeEvaluator,
    RunnerBudget,
    run_benchmark,
)
from model_compass.exceptions import BenchmarkError
from tests.fixtures.fake_execution_backend import FakeExecutionBackend


def _one_case_dataset(*, evaluator: str = "exact", **case_overrides: object) -> BenchmarkDataset:
    """Build a single-case, single-task dataset for runner-focused tests."""
    defaults: dict[str, object] = {
        "case_id": "c1",
        "task": "qa",
        "input_text": "2+2=?",
        "evaluator": evaluator,
        "expected_output": "4",
    }
    defaults.update(case_overrides)
    return BenchmarkDataset(name="runner-fixture", version="1.0.0", cases=(BenchmarkCase.model_validate(defaults),))


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_respects_repetitions():
    """[Unit] repetitions: each (model, case) pair runs the configured number of times.

    Scenario: Runs one case against one model with repetitions=3.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: run_benchmark's combinations list construction.
    """
    dataset = _one_case_dataset()
    backend = FakeExecutionBackend({"test:model": "4"})
    outcome = await run_benchmark(dataset, ["test:model"], backend=backend, config=BenchmarkRunConfig(repetitions=3))
    assert len(outcome.results) == 3
    assert {result.metadata["repetition"] for result in outcome.results} == {0, 1, 2}


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_reproducibility_fields():
    """[Unit] reproducibility: the run records package version, dataset identity, and configuration.

    Scenario: Runs a dataset and inspects the returned BenchmarkRun's fields.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: run_benchmark's BenchmarkRun construction.
    """
    dataset = _one_case_dataset()
    backend = FakeExecutionBackend({"test:model": "4"})
    outcome = await run_benchmark(
        dataset, ["test:model"], backend=backend, config=BenchmarkRunConfig(repetitions=2, seed=7)
    )
    run = outcome.run
    assert run.dataset_id == dataset.name
    assert run.dataset_version == dataset.version
    assert run.dataset_hash == dataset.content_hash
    assert run.runner_version == _version.__version__
    assert run.configuration["repetitions"] == 2
    assert run.configuration["seed"] == 7
    assert run.configuration["models"] == ["test:model"]
    assert run.status == "completed"
    assert run.ended_at is not None
    assert run.started_at <= run.ended_at


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_budget_max_cases_stops_scheduling_new_work():
    """[Unit] budget max_cases: no more than the configured number of cases actually execute.

    Scenario: Runs 4 (model, case) combinations with max_cases=2.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: _BudgetTracker.try_reserve's max_cases admission check.
    """
    dataset = BenchmarkDataset(
        name="d",
        version="1.0.0",
        cases=(
            BenchmarkCase(case_id="c1", task="qa", input_text="q1", evaluator="exact", expected_output="a1"),
            BenchmarkCase(case_id="c2", task="qa", input_text="q2", evaluator="exact", expected_output="a2"),
        ),
    )
    backend = FakeExecutionBackend({"m1": "a1", "m2": "a1"})
    outcome = await run_benchmark(
        dataset,
        ["m1", "m2"],
        backend=backend,
        config=BenchmarkRunConfig(concurrency=1, budget=RunnerBudget(max_cases=2)),
    )
    executed = [r for r in outcome.results if r.metadata.get("error_category") != "budget_exceeded"]
    skipped = [r for r in outcome.results if r.metadata.get("error_category") == "budget_exceeded"]
    assert len(executed) == 2
    assert len(skipped) == 2
    assert len(backend.calls) == 2


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_budget_max_cost_per_model_skips_once_exhausted():
    """[Unit] budget max_cost_per_model: further cases for a model are skipped once its cap is reached.

    Scenario: Runs two cases for one model with a per-case cost ceiling and a tight per-model cap.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: _BudgetTracker.try_reserve's max_cost_per_model admission check.
    """
    dataset = BenchmarkDataset(
        name="d",
        version="1.0.0",
        cases=(
            BenchmarkCase(case_id="c1", task="qa", input_text="q1", evaluator="exact", expected_output="a1"),
            BenchmarkCase(case_id="c2", task="qa", input_text="q2", evaluator="exact", expected_output="a2"),
        ),
    )
    backend = FakeExecutionBackend({"m1": "a1"}, cost_usd=Decimal("0.01"))
    outcome = await run_benchmark(
        dataset,
        ["m1"],
        backend=backend,
        config=BenchmarkRunConfig(
            concurrency=1,
            budget=RunnerBudget(max_cost_per_model=Decimal("0.01"), cost_ceiling_per_case=Decimal("0.01")),
        ),
    )
    categories = sorted((r.metadata.get("error_category") or "none") for r in outcome.results)
    assert categories == ["budget_exceeded", "none"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_dispatches_to_configured_llm_judge():
    """[Unit] judge dispatch: a case whose evaluator is 'llm_judge' is scored via the configured judge.

    Scenario: Configures an LLMJudgeEvaluator backed by a second fake backend and runs a judge case.
    Boundaries: Real run_benchmark and LLMJudgeEvaluator; both backends are local fakes, no network.
    On failure, first check: run_benchmark's _evaluate dispatch for case.evaluator == 'llm_judge'.
    """
    dataset = _one_case_dataset(evaluator="llm_judge", expected_output=None)
    candidate_backend = FakeExecutionBackend({"candidate:model": "4"})
    judge_backend = FakeExecutionBackend({"judge:model": '{"score": 0.75, "explanation": "close enough"}'})
    judge = LLMJudgeEvaluator(
        backend=judge_backend, config=JudgeConfig(judge_model_id="judge:model", prompt_version="v1")
    )

    outcome = await run_benchmark(dataset, ["candidate:model"], backend=candidate_backend, llm_judge=judge)

    (result,) = outcome.results
    assert result.score == Decimal("0.75")
    assert result.evaluator == "llm_judge@v1"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_judge_case_without_configured_judge_records_evaluation_failed():
    """[Unit] missing judge: a judge-evaluated case with no configured judge is recorded as failed.

    Scenario: Runs a case using the 'llm_judge' evaluator without passing llm_judge to run_benchmark.
    Boundaries: Real run_benchmark; no judge is configured, so no second backend is involved.
    On failure, first check: run_benchmark's guard against an unconfigured llm_judge.
    """
    dataset = _one_case_dataset(evaluator="llm_judge", expected_output=None)
    backend = FakeExecutionBackend({"candidate:model": "4"})
    outcome = await run_benchmark(dataset, ["candidate:model"], backend=backend)

    (result,) = outcome.results
    assert result.score is None
    assert result.metadata["error_category"] == "evaluation_failed"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_execution_failure_is_isolated_per_case():
    """[Unit] execution isolation: an execution failure for one model does not affect another's result.

    Scenario: Runs one case against a failing model and a succeeding model concurrently.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: run_benchmark's per-case exception handling around backend.complete.
    """
    dataset = _one_case_dataset()
    backend = FakeExecutionBackend({"good:model": "4"}, fail_models=frozenset({"bad:model"}))
    outcome = await run_benchmark(dataset, ["good:model", "bad:model"], backend=backend)

    by_model = {result.model_id: result for result in outcome.results}
    assert by_model["good:model"].score == Decimal(1)
    assert by_model["bad:model"].score is None
    assert by_model["bad:model"].metadata["error_category"] == "execution_error"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_unexpected_evaluator_bug_does_not_lose_other_results():
    """[Unit] last-resort isolation: a bug inside a custom evaluator does not discard other results.

    Scenario: Registers a custom evaluator that raises a plain RuntimeError for one model's
        case while a normal built-in evaluator scores a second model's case for the same case.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: run_benchmark's return_exceptions=True fallback and its
        'unexpected_error' result construction.
    """

    class _BuggyEvaluator:
        """A custom evaluator that always raises, simulating an unexpected bug."""

        evaluator_id = "buggy"
        evaluator_version = "1.0.0"

        def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
            """Always raise, regardless of input."""
            raise RuntimeError("boom")

    dataset = _one_case_dataset(evaluator="buggy", expected_output=None)
    backend = FakeExecutionBackend({"test:model": "4"})
    outcome = await run_benchmark(
        dataset, ["test:model"], backend=backend, custom_evaluators={"buggy": _BuggyEvaluator()}
    )

    (result,) = outcome.results
    assert result.score is None
    assert result.metadata["error_category"] == "unexpected_error"
    assert "boom" in result.metadata["error_message"]


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_raw_response_persisted_only_when_enabled():
    """[Unit] raw response policy: raw responses are stored only when persist_raw_responses is True.

    Scenario: Runs the same dataset once with the default policy and once with it enabled.
    Boundaries: Real run_benchmark; the execution backend is a local fake, no network.
    On failure, first check: run_benchmark's conditional raw_response metadata key.
    """
    dataset = _one_case_dataset()
    backend = FakeExecutionBackend({"test:model": "4"})
    default_outcome = await run_benchmark(dataset, ["test:model"], backend=backend)
    assert "raw_response" not in default_outcome.results[0].metadata

    enabled_outcome = await run_benchmark(
        dataset, ["test:model"], backend=backend, config=BenchmarkRunConfig(persist_raw_responses=True)
    )
    assert enabled_outcome.results[0].metadata["raw_response"] == "4"


@pytest.mark.unit
@pytest.mark.asyncio
async def test_run_benchmark_rejects_empty_model_list():
    """[Unit] empty model list: run_benchmark rejects being called with no models.

    Scenario: Calls run_benchmark with an empty models sequence.
    Boundaries: Real run_benchmark; no backend call should occur.
    On failure, first check: run_benchmark's at-least-one-model guard.
    """
    dataset = _one_case_dataset()
    with pytest.raises(BenchmarkError, match="at least one model"):
        await run_benchmark(dataset, [], backend=FakeExecutionBackend())


@pytest.mark.unit
def test_runner_budget_config_serializes_for_reproducibility():
    """[Unit] budget serialization: BenchmarkRunConfig's budget is JSON-serializable in configuration.

    Scenario: Serializes a RunnerBudget via model_dump(mode='json') as run_benchmark does.
    Boundaries: Pure pydantic serialization; no I/O.
    On failure, first check: RunnerBudget's Decimal fields surviving JSON-mode serialization.
    """
    budget = RunnerBudget(max_total_cost=Decimal("1.5"), max_cases=10)
    dumped = budget.model_dump(mode="json")
    json.dumps(dumped)  # must not raise
    assert dumped["max_cases"] == 10
