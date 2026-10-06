"""Synchronous scoring of pre-collected outputs, for single-task datasets with no execution backend."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from model_compass.benchmarks.dataset import BenchmarkDataset
from model_compass.benchmarks.evaluators import EvaluationContext, Evaluator, resolve_evaluator
from model_compass.exceptions import BenchmarkError
from model_compass.metrics.task_observations import QualityEvidence


class OfflineCaseEvaluation(BaseModel):
    """One case's score from offline evaluation."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    score: Decimal
    passed: Optional[bool]
    explanation: str


class OfflineBenchmarkReport(BaseModel):
    """Aggregate offline evaluation outcome for one model against one task."""

    model_config = ConfigDict(frozen=True)

    dataset: str
    dataset_version: str
    task: str
    model_id: str
    sample_size: int
    passed: int
    quality_score: Decimal
    cases: tuple[OfflineCaseEvaluation, ...]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_quality_evidence(self) -> QualityEvidence:
        """Convert the report into task-selection quality evidence."""
        return QualityEvidence(
            model_id=self.model_id,
            task=self.task,
            quality_score=self.quality_score,
            sample_size=self.sample_size,
            source="benchmark",
            evaluator_type="offline_aggregate",
            dataset=self.dataset,
            evaluated_at=self.evaluated_at,
        )


def evaluate_offline(
    dataset: BenchmarkDataset,
    outputs: Mapping[str, str],
    *,
    model_id: str,
    custom_evaluators: Optional[Mapping[str, Evaluator]] = None,
) -> OfflineBenchmarkReport:
    """Score pre-collected string outputs against a single-task dataset.

    No execution backend is used; outputs must already exist (e.g. collected
    manually, or from a provider's own console). A case missing from `outputs`
    is scored as a fail, not skipped. Datasets spanning more than one task, or
    using the `llm_judge` evaluator, are rejected - use `run_benchmark` instead,
    since both require an execution backend and task-aware aggregation.
    """
    if not dataset.cases:
        raise BenchmarkError("dataset must contain at least one case")
    tasks = dataset.tasks()
    if len(tasks) != 1:
        raise BenchmarkError(f"offline evaluation requires a single-task dataset; found tasks: {', '.join(tasks)}")
    task = tasks[0]
    known_ids = {case.case_id for case in dataset.cases}
    unknown = set(outputs) - known_ids
    if unknown:
        raise BenchmarkError(f"outputs contain unknown case ids: {', '.join(sorted(unknown))}")

    context = EvaluationContext(model_id=model_id, dataset_name=dataset.name)
    evaluations: list[OfflineCaseEvaluation] = []
    for case in dataset.cases:
        if case.evaluator == "llm_judge":
            raise BenchmarkError(f"case {case.case_id!r} uses the llm_judge evaluator; use run_benchmark instead")
        if case.case_id not in outputs:
            evaluations.append(
                OfflineCaseEvaluation(
                    case_id=case.case_id,
                    score=Decimal(0),
                    passed=False,
                    explanation="no output was provided for this case",
                )
            )
            continue
        evaluator = resolve_evaluator(case.evaluator, custom_evaluators=custom_evaluators)
        result = evaluator.evaluate(case, outputs[case.case_id], context)
        evaluations.append(
            OfflineCaseEvaluation(
                case_id=case.case_id, score=result.score, passed=result.passed, explanation=result.explanation
            )
        )

    sample_size = len(evaluations)
    passed_count = sum(1 for item in evaluations if item.passed)
    quality_score = sum((item.score for item in evaluations), Decimal(0)) / Decimal(sample_size)
    return OfflineBenchmarkReport(
        dataset=dataset.name,
        dataset_version=dataset.version,
        task=task,
        model_id=model_id,
        sample_size=sample_size,
        passed=passed_count,
        quality_score=quality_score,
        cases=tuple(evaluations),
    )
