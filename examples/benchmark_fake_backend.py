from __future__ import annotations

import asyncio
import json
from decimal import Decimal

from model_compass.benchmarks import BenchmarkCase, BenchmarkDataset, BenchmarkRunConfig, RunnerBudget, run_benchmark
from model_compass.execution import ExecutionBackend, ExecutionRequest, ExecutionResult


class FakeBackend(ExecutionBackend):
    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        return ExecutionResult(
            model_id=request.model_id,
            task=request.task,
            output_text="Paris",
            latency_ms=25,
            input_tokens=12,
            output_tokens=1,
            actual_cost_usd=Decimal("0.001"),
            finish_reason="stop",
        )


async def run_example() -> dict[str, object]:
    dataset = BenchmarkDataset(
        name="demo",
        version="1.0.0",
        cases=(
            BenchmarkCase(
                case_id="capital-of-france",
                task="qa",
                input_text="What is the capital of France?",
                evaluator="exact",
                expected_output="Paris",
            ),
        ),
    )
    outcome = await run_benchmark(
        dataset,
        ["demo:small"],
        backend=FakeBackend(),
        config=BenchmarkRunConfig(repetitions=1, concurrency=1, budget=RunnerBudget(max_total_cost=Decimal("0.01"))),
    )
    return {
        "dataset": outcome.run.dataset_id,
        "results": len(outcome.results),
        "score": str(outcome.results[0].score),
    }


def main() -> int:
    print(json.dumps(asyncio.run(run_example()), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
