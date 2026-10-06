"""Benchmark execution: a provider-independent, budget-aware, concurrent runner."""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass._version import __version__ as _package_version
from model_compass.benchmarks.aggregation import ScoredCase
from model_compass.benchmarks.dataset import BenchmarkCase, BenchmarkDataset
from model_compass.benchmarks.evaluators import EvaluationContext, EvaluationResult, Evaluator, resolve_evaluator
from model_compass.benchmarks.judge import JudgeEvaluationError, LLMJudgeEvaluator
from model_compass.domain import BenchmarkResult, BenchmarkRun
from model_compass.exceptions import BenchmarkError
from model_compass.execution.backend import CompletionRequest, ExecutionBackend, ExecutionError

_logger = logging.getLogger(__name__)


class RunnerBudget(BaseModel):
    """Conservative, best-effort cost controls for a live benchmark run.

    Enforcement is advisory: admission uses `cost_ceiling_per_case` (or, absent
    that, the running average of a model's completed costs so far) as a
    pre-call estimate. Provider billing that differs from the reported
    response cost, or that arrives after execution, is not detected here.
    """

    model_config = ConfigDict(frozen=True)

    max_total_cost: Optional[Decimal] = Field(default=None, ge=0)
    max_cost_per_model: Optional[Decimal] = Field(default=None, ge=0)
    max_cases: Optional[int] = Field(default=None, ge=1)
    cost_ceiling_per_case: Optional[Decimal] = Field(default=None, ge=0)


class BenchmarkRunConfig(BaseModel):
    """Execution parameters for one `run_benchmark` call."""

    model_config = ConfigDict(frozen=True)

    repetitions: int = Field(default=1, ge=1)
    concurrency: int = Field(default=1, ge=1)
    persist_raw_responses: bool = False
    budget: Optional[RunnerBudget] = None
    seed: Optional[int] = None
    model_parameters: dict[str, dict[str, Any]] = Field(default_factory=dict)

    @field_validator("model_parameters")
    @classmethod
    def _copy_parameters(cls, value: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
        """Defensively copy per-model parameter dicts so callers cannot mutate them later."""
        return {model_id: dict(parameters) for model_id, parameters in value.items()}


class BenchmarkRunOutcome(BaseModel):
    """A completed run's reproducible metadata, per-case results, and scored pairs."""

    model_config = ConfigDict(frozen=True)

    run: BenchmarkRun
    results: tuple[BenchmarkResult, ...]
    scored_cases: tuple[ScoredCase, ...]


async def run_benchmark(
    dataset: BenchmarkDataset,
    models: Sequence[str],
    *,
    backend: ExecutionBackend,
    custom_evaluators: Optional[Mapping[str, Evaluator]] = None,
    llm_judge: Optional[LLMJudgeEvaluator] = None,
    config: Optional[BenchmarkRunConfig] = None,
    now_utc: Optional[datetime] = None,
) -> BenchmarkRunOutcome:
    """Run a dataset against one or more models and return reproducible results.

    Every case for every model and repetition is isolated: a failed execution,
    a failed evaluation, or a budget-exhausted skip produces its own
    `BenchmarkResult` with `score=None` and an `error_category`, rather than
    raising and discarding results already produced by other cases.
    """
    if not models:
        raise BenchmarkError("at least one model must be given")
    cfg = config or BenchmarkRunConfig()
    started_at = now_utc or datetime.now(UTC)
    run_id = str(uuid4())
    tracker = _BudgetTracker(cfg.budget)
    semaphore = asyncio.Semaphore(cfg.concurrency)

    combinations = [
        (model_id, case, repetition)
        for model_id in models
        for case in dataset.cases
        for repetition in range(cfg.repetitions)
    ]
    coroutines = [
        _execute_case(
            model_id,
            case,
            repetition,
            backend=backend,
            run_id=run_id,
            dataset=dataset,
            evaluators=custom_evaluators or {},
            llm_judge=llm_judge,
            persist_raw_responses=cfg.persist_raw_responses,
            model_parameters=cfg.model_parameters,
            tracker=tracker,
            semaphore=semaphore,
        )
        for model_id, case, repetition in combinations
    ]
    outcomes = await asyncio.gather(*coroutines, return_exceptions=True)

    results: list[BenchmarkResult] = []
    scored: list[ScoredCase] = []
    for (model_id, case, repetition), outcome in zip(combinations, outcomes, strict=True):
        if isinstance(outcome, BaseException):
            _logger.exception("Unexpected error running case %r for %r", case.case_id, model_id, exc_info=outcome)
            results.append(
                _error_result(
                    run_id,
                    case,
                    model_id,
                    dataset=dataset,
                    repetition=repetition,
                    error_category="unexpected_error",
                    error_message=str(outcome),
                )
            )
            continue
        result, scored_case = outcome
        results.append(result)
        if scored_case is not None:
            scored.append(scored_case)

    ended_at = datetime.now(UTC)
    run = BenchmarkRun(
        run_id=run_id,
        dataset_id=dataset.name,
        dataset_version=dataset.version,
        dataset_hash=dataset.content_hash,
        started_at=started_at,
        ended_at=ended_at,
        runner_version=_package_version,
        configuration={
            "models": list(models),
            "repetitions": cfg.repetitions,
            "concurrency": cfg.concurrency,
            "seed": cfg.seed,
            "persist_raw_responses": cfg.persist_raw_responses,
            "model_parameters": cfg.model_parameters,
            "budget": cfg.budget.model_dump(mode="json") if cfg.budget is not None else None,
        },
        status="completed",
    )
    return BenchmarkRunOutcome(run=run, results=tuple(results), scored_cases=tuple(scored))


class _BudgetTracker:
    """Reserve-then-settle cost accounting shared across concurrently running cases."""

    def __init__(self, budget: Optional[RunnerBudget]):
        """Store the budget and initialize empty reservation and completion state."""
        self._budget = budget
        self._lock = asyncio.Lock()
        self._reserved_total = Decimal(0)
        self._reserved_per_model: dict[str, Decimal] = {}
        self._completed_costs: dict[str, list[Decimal]] = {}
        self._scheduled_cases = 0

    async def try_reserve(self, model_id: str) -> Optional[Decimal]:
        """Admit one case against the budget, returning its reserved estimate, or None if it would exceed budget."""
        if self._budget is None:
            return Decimal(0)
        async with self._lock:
            if self._budget.max_cases is not None and self._scheduled_cases >= self._budget.max_cases:
                return None
            estimate = self._estimate_for(model_id)
            if (
                self._budget.max_total_cost is not None
                and self._reserved_total + estimate > self._budget.max_total_cost
            ):
                return None
            reserved_for_model = self._reserved_per_model.get(model_id, Decimal(0))
            if (
                self._budget.max_cost_per_model is not None
                and reserved_for_model + estimate > self._budget.max_cost_per_model
            ):
                return None
            self._reserved_total += estimate
            self._reserved_per_model[model_id] = reserved_for_model + estimate
            self._scheduled_cases += 1
            return estimate

    async def settle(self, model_id: str, reserved: Decimal, actual: Optional[Decimal]):
        """Replace a reservation with the actual cost once a call completes."""
        settled = actual if actual is not None else Decimal(0)
        async with self._lock:
            self._reserved_total += settled - reserved
            self._reserved_per_model[model_id] = self._reserved_per_model.get(model_id, Decimal(0)) + settled - reserved
            self._completed_costs.setdefault(model_id, []).append(settled)

    def _estimate_for(self, model_id: str) -> Decimal:
        """Return the conservative pre-call cost estimate for a model."""
        if self._budget is not None and self._budget.cost_ceiling_per_case is not None:
            return self._budget.cost_ceiling_per_case
        history = self._completed_costs.get(model_id)
        if not history:
            return Decimal(0)
        return sum(history, Decimal(0)) / Decimal(len(history))


async def _execute_case(
    model_id: str,
    case: BenchmarkCase,
    repetition: int,
    *,
    backend: ExecutionBackend,
    run_id: str,
    dataset: BenchmarkDataset,
    evaluators: Mapping[str, Evaluator],
    llm_judge: Optional[LLMJudgeEvaluator],
    persist_raw_responses: bool,
    model_parameters: Mapping[str, dict[str, Any]],
    tracker: _BudgetTracker,
    semaphore: asyncio.Semaphore,
) -> tuple[BenchmarkResult, Optional[ScoredCase]]:
    """Run, evaluate, and record one (model, case, repetition) triple."""
    async with semaphore:
        reserved = await tracker.try_reserve(model_id)
        if reserved is None:
            return (
                _error_result(
                    run_id, case, model_id, dataset=dataset, repetition=repetition, error_category="budget_exceeded"
                ),
                None,
            )

        request = CompletionRequest(
            model_id=model_id,
            task=case.task,
            messages=list(case.prompt_messages()),
            parameters=dict(model_parameters.get(model_id, {})),
        )
        try:
            execution = await backend.execute(request)
        except ExecutionError as exc:
            await tracker.settle(model_id, reserved, None)
            return (
                _error_result(
                    run_id,
                    case,
                    model_id,
                    dataset=dataset,
                    repetition=repetition,
                    error_category="execution_error",
                    error_message=str(exc),
                    latency_ms=exc.latency_ms,
                ),
                None,
            )
        await tracker.settle(model_id, reserved, execution.actual_cost_usd)

        context = EvaluationContext(model_id=model_id, dataset_name=dataset.name, repetition_index=repetition)
        try:
            evaluation = await _evaluate(case, execution.output_text, context, evaluators, llm_judge)
        except (JudgeEvaluationError, BenchmarkError) as exc:
            _logger.info("Case %r failed evaluation for %r: %s", case.case_id, model_id, exc)
            return (
                _error_result(
                    run_id,
                    case,
                    model_id,
                    dataset=dataset,
                    repetition=repetition,
                    error_category="evaluation_failed",
                    error_message=str(exc),
                    cost=execution.actual_cost_usd,
                    latency_ms=execution.latency_ms,
                    execution_succeeded=True,
                ),
                None,
            )

        judge_cost_raw = evaluation.details.get("judge_cost_usd")
        result = BenchmarkResult(
            run_id=run_id,
            case_id=case.case_id,
            model_id=model_id,
            score=evaluation.score,
            evaluator=f"{evaluation.evaluator_id}@{evaluation.evaluator_version}",
            cost=execution.actual_cost_usd,
            latency_ms=Decimal(execution.latency_ms),
            metadata={
                "task": case.task,
                "tags": list(case.tags),
                "dataset": dataset.name,
                "repetition": repetition,
                "execution_succeeded": True,
                "passed": evaluation.passed,
                "explanation": evaluation.explanation,
                "input_tokens": execution.input_tokens,
                "output_tokens": execution.output_tokens,
                "judge_cost_usd": judge_cost_raw,
                **({"raw_response": execution.output_text} if persist_raw_responses else {}),
            },
        )
        return result, ScoredCase(case=case, result=result, dataset_name=dataset.name)


async def _evaluate(
    case: BenchmarkCase,
    response: str,
    context: EvaluationContext,
    evaluators: Mapping[str, Evaluator],
    llm_judge: Optional[LLMJudgeEvaluator],
) -> EvaluationResult:
    """Dispatch to the LLM judge, a sync evaluator, or an async custom evaluator."""
    if case.evaluator == "llm_judge":
        if llm_judge is None:
            raise BenchmarkError(f"case {case.case_id!r} requires an llm_judge evaluator but none was configured")
        return await llm_judge.evaluate(case, response, context)
    evaluator = resolve_evaluator(case.evaluator, custom_evaluators=evaluators)
    outcome = evaluator.evaluate(case, response, context)
    if inspect.isawaitable(outcome):
        return await outcome
    return outcome


def _error_result(
    run_id: str,
    case: BenchmarkCase,
    model_id: str,
    *,
    dataset: BenchmarkDataset,
    repetition: int,
    error_category: str,
    error_message: Optional[str] = None,
    cost: Optional[Decimal] = None,
    latency_ms: Optional[int] = None,
    execution_succeeded: bool = False,
) -> BenchmarkResult:
    """Build a BenchmarkResult for a case that did not produce a score."""
    return BenchmarkResult(
        run_id=run_id,
        case_id=case.case_id,
        model_id=model_id,
        score=None,
        evaluator=None,
        cost=cost,
        latency_ms=Decimal(latency_ms) if latency_ms is not None else None,
        metadata={
            "task": case.task,
            "tags": list(case.tags),
            "dataset": dataset.name,
            "repetition": repetition,
            "execution_succeeded": execution_succeeded,
            "error_category": error_category,
            "error_message": error_message,
        },
    )
