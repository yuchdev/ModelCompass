"""Deterministic offline benchmark evaluation."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from model_compass.exceptions import BenchmarkError
from model_compass.metrics import QualityEvidence

_logger = logging.getLogger(__name__)


class EvaluatorType(StrEnum):
    """Built-in deterministic evaluators."""

    EXACT = "exact"
    REGEX = "regex"
    JSON = "json"


class BenchmarkCase(BaseModel):
    """One benchmark input and its expected result."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    input_text: str
    expected_output: str


class BenchmarkDataset(BaseModel):
    """Task-scoped cases evaluated with one deterministic method."""

    model_config = ConfigDict(frozen=True)

    name: str
    task: str
    evaluator: EvaluatorType
    cases: tuple[BenchmarkCase, ...]


class CaseEvaluation(BaseModel):
    """Outcome for a single benchmark case."""

    model_config = ConfigDict(frozen=True)

    case_id: str
    passed: bool


class BenchmarkReport(BaseModel):
    """Reproducible aggregate quality evidence for one model."""

    model_config = ConfigDict(frozen=True)

    dataset: str
    task: str
    model_id: str
    evaluator: EvaluatorType
    sample_size: int
    passed: int
    quality_score: Decimal
    cases: tuple[CaseEvaluation, ...]
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def to_quality_evidence(self) -> QualityEvidence:
        """Convert report to provenance-bearing task quality evidence."""
        return QualityEvidence(
            model_id=self.model_id,
            task=self.task,
            quality_score=self.quality_score,
            sample_size=self.sample_size,
            source="benchmark",
            evaluator_type=self.evaluator.value,
            dataset=self.dataset,
            evaluated_at=self.evaluated_at,
        )


def evaluate_benchmark(
    dataset: BenchmarkDataset,
    outputs: Mapping[str, str],
    *,
    model_id: str,
) -> BenchmarkReport:
    """Score supplied model outputs without making network calls."""
    if not dataset.cases:
        raise BenchmarkError("benchmark dataset must contain at least one case")
    case_ids = [case.case_id for case in dataset.cases]
    duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
    if duplicates:
        raise BenchmarkError(f"benchmark dataset contains duplicate case ids: {', '.join(duplicates)}")
    unknown = set(outputs) - {case.case_id for case in dataset.cases}
    if unknown:
        raise BenchmarkError(f"outputs contain unknown case ids: {', '.join(sorted(unknown))}")

    results = tuple(
        CaseEvaluation(
            case_id=case.case_id,
            passed=case.case_id in outputs and _matches(dataset.evaluator, case.expected_output, outputs[case.case_id]),
        )
        for case in dataset.cases
    )
    passed = sum(result.passed for result in results)
    return BenchmarkReport(
        dataset=dataset.name,
        task=dataset.task,
        model_id=model_id,
        evaluator=dataset.evaluator,
        sample_size=len(results),
        passed=passed,
        quality_score=Decimal(passed) / Decimal(len(results)),
        cases=results,
    )


def _matches(evaluator: EvaluatorType, expected: str, actual: str) -> bool:
    """Return whether the actual output satisfies the expected value for an evaluator."""
    if evaluator == EvaluatorType.EXACT:
        return expected == actual
    if evaluator == EvaluatorType.REGEX:
        try:
            return re.fullmatch(expected, actual) is not None
        except re.error as exc:
            raise BenchmarkError(f"invalid regex evaluator pattern: {exc}") from exc
    if evaluator == EvaluatorType.JSON:
        try:
            return bool(json.loads(expected) == json.loads(actual))
        except (json.JSONDecodeError, TypeError):
            _logger.debug("Treating non-matching JSON evaluator case as a mismatch")
            return False
    raise BenchmarkError(f"unsupported evaluator: {evaluator}")
