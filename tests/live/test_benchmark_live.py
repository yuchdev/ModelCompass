from __future__ import annotations

import os
from decimal import Decimal

import pytest

from model_compass.benchmarks import BenchmarkCase, BenchmarkDataset, BenchmarkRunConfig, RunnerBudget, run_benchmark
from model_compass.execution import LiteLLMBackend


@pytest.mark.live
@pytest.mark.asyncio
async def test_benchmark_live_smoke_with_explicit_model_and_budget():
    """[E2E] live benchmark smoke: a tiny dataset runs against one named model under an explicit budget.

    Scenario: Runs a one-case arithmetic dataset against exactly one explicitly named,
        opted-in model with an explicit cost ceiling, and checks the run completes.
    Boundaries: Real LiteLLM HTTP call to whichever provider the named model belongs to;
        runs only when opted in via env vars naming a model and an explicit budget.
    On failure, first check: live provider response drift in message content format.
    """
    if os.getenv("MODEL_ANALYTICS_LIVE_BENCHMARK") != "1":
        pytest.skip("Set MODEL_ANALYTICS_LIVE_BENCHMARK=1 to run the live benchmark smoke test")
    model_id = os.getenv("MODEL_ANALYTICS_LIVE_BENCHMARK_MODEL")
    budget_usd = os.getenv("MODEL_ANALYTICS_LIVE_BENCHMARK_BUDGET_USD")
    if not model_id or not budget_usd:
        pytest.skip(
            "Set MODEL_ANALYTICS_LIVE_BENCHMARK_MODEL (a single LiteLLM model id) and "
            "MODEL_ANALYTICS_LIVE_BENCHMARK_BUDGET_USD (an explicit cost acknowledgement) "
            "to run the live benchmark smoke test. Never run this against a whole catalog."
        )

    dataset = BenchmarkDataset(
        name="live-arithmetic-smoke",
        version="1.0.0",
        cases=(
            BenchmarkCase(
                case_id="one",
                task="qa",
                input_text="What is 2+2? Answer with only the digit.",
                evaluator="exact",
                expected_output="4",
            ),
        ),
    )
    outcome = await run_benchmark(
        dataset,
        [model_id],
        backend=LiteLLMBackend(),
        config=BenchmarkRunConfig(
            repetitions=1,
            concurrency=1,
            budget=RunnerBudget(max_total_cost=Decimal(budget_usd), max_cases=1),
        ),
    )

    assert len(outcome.results) == 1
    result = outcome.results[0]
    assert result.metadata.get("execution_succeeded") is True
    assert result.score is not None
