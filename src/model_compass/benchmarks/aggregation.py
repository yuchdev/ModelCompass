"""Task-aware quality aggregation with deterministic bootstrap confidence intervals."""

from __future__ import annotations

import random
import statistics
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from decimal import Decimal
from math import ceil
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from model_compass.benchmarks.dataset import BenchmarkCase
from model_compass.domain import BenchmarkResult, QualityEvidence
from model_compass.exceptions import BenchmarkError

GroupKind = Literal["task", "dataset", "tag", "overall"]


class ScoredCase(BaseModel):
    """A case paired with its result, for aggregation independent of storage shape."""

    model_config = ConfigDict(frozen=True)

    case: BenchmarkCase
    result: BenchmarkResult
    dataset_name: str


class ConfidenceInterval(BaseModel):
    """A bootstrap percentile interval; a method/seed are recorded, not implied."""

    model_config = ConfigDict(frozen=True)

    lower: Decimal
    upper: Decimal
    level: Decimal = Decimal("0.95")
    method: str = "bootstrap_percentile"
    iterations: int = 2000
    seed: int = 0


class QualitySummary(BaseModel):
    """Aggregate quality for one model within one explicit, named grouping."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    group_kind: GroupKind
    group_key: Optional[str]
    mean_score: Decimal
    median_score: Decimal
    pass_rate: Optional[Decimal] = None
    sample_count: int = Field(ge=1)
    confidence_interval: Optional[ConfidenceInterval] = None
    dataset_refs: tuple[str, ...] = ()

    def to_quality_evidence(self, *, evaluated_at: Optional[datetime] = None) -> QualityEvidence:
        """Convert this summary into persistable, provenance-bearing quality evidence."""
        task = self.group_key if self.group_kind == "task" else None
        return QualityEvidence(
            model_id=self.model_id,
            task=task,
            score=self.mean_score,
            evaluator="aggregate",
            source="benchmark",
            sample_count=self.sample_count,
            observed_at=evaluated_at or datetime.now(UTC),
            metadata={
                "group_kind": self.group_kind,
                "group_key": self.group_key,
                "dataset_refs": list(self.dataset_refs),
                "median_score": str(self.median_score),
                "pass_rate": str(self.pass_rate) if self.pass_rate is not None else None,
            },
        )


def bootstrap_confidence_interval(
    scores: Sequence[Decimal],
    *,
    level: Decimal = Decimal("0.95"),
    iterations: int = 2000,
    seed: int = 0,
) -> ConfidenceInterval:
    """Return a deterministic bootstrap percentile confidence interval for the mean.

    Resamples `scores` with replacement `iterations` times using a seeded RNG,
    so the same scores and seed always produce the same interval. This is a
    standard, dependency-free method, not a claim of exact sampling theory.
    """
    if len(scores) < 2:
        raise BenchmarkError("bootstrap confidence interval requires at least two scores")
    if not level.is_finite() or not Decimal("0") < level < Decimal("1"):
        raise ValueError("level must be a finite value strictly between 0 and 1")
    if iterations < 1:
        raise ValueError("iterations must be at least one")
    rng = random.Random(seed)
    n = len(scores)
    means = sorted(_mean(rng.choices(scores, k=n)) for _ in range(iterations))
    tail = (Decimal(1) - level) / Decimal(2)
    lower_index = max(0, ceil(float(tail) * iterations) - 1)
    upper_index = min(iterations - 1, ceil(float(Decimal(1) - tail) * iterations) - 1)
    return ConfidenceInterval(
        lower=means[lower_index],
        upper=means[upper_index],
        level=level,
        iterations=iterations,
        seed=seed,
    )


def summarize_quality(
    scored_cases: Sequence[ScoredCase],
    *,
    group_by: GroupKind,
    weights: Optional[Mapping[str, Decimal]] = None,
    confidence_level: Decimal = Decimal("0.95"),
    bootstrap_iterations: int = 2000,
    seed: int = 0,
) -> tuple[QualitySummary, ...]:
    """Group scored cases by model and the requested dimension, then summarize each group.

    `group_by="overall"` requires explicit `weights` mapping task name to weight;
    scores are never averaged across unrelated tasks without caller-supplied
    weighting, and a task present in the data but missing from `weights` raises.
    """
    if group_by == "overall" and not weights:
        raise BenchmarkError("group_by='overall' requires explicit per-task weights")

    by_model: dict[str, list[ScoredCase]] = {}
    for scored in scored_cases:
        by_model.setdefault(scored.result.model_id, []).append(scored)

    summaries: list[QualitySummary] = []
    for model_id in sorted(by_model):
        rows = by_model[model_id]
        if group_by == "overall":
            summaries.append(
                _summarize_overall(model_id, rows, weights or {}, confidence_level, bootstrap_iterations, seed)
            )
            continue
        groups: dict[str, list[ScoredCase]] = {}
        for scored in rows:
            keys = _group_keys(scored, group_by)
            for key in keys:
                groups.setdefault(key, []).append(scored)
        for key in sorted(groups):
            summary = _summarize_group(
                model_id, group_by, key, groups[key], confidence_level, bootstrap_iterations, seed
            )
            if summary is not None:
                summaries.append(summary)
    return tuple(summaries)


def _group_keys(scored: ScoredCase, group_by: GroupKind) -> tuple[str, ...]:
    """Return the group key(s) a scored case belongs to for the given dimension."""
    if group_by == "task":
        return (scored.case.task,)
    if group_by == "dataset":
        return (scored.dataset_name,)
    if group_by == "tag":
        return scored.case.tags
    raise BenchmarkError(f"unsupported group_by: {group_by}")


def _summarize_group(
    model_id: str,
    group_by: GroupKind,
    key: str,
    rows: list[ScoredCase],
    confidence_level: Decimal,
    bootstrap_iterations: int,
    seed: int,
) -> Optional[QualitySummary]:
    """Build one group's QualitySummary, or None if it has no scored cases."""
    scores = [row.result.score for row in rows if row.result.score is not None]
    if not scores:
        return None
    return QualitySummary(
        model_id=model_id,
        group_kind=group_by,
        group_key=key,
        mean_score=_mean(scores),
        median_score=Decimal(str(statistics.median(scores))),
        pass_rate=_pass_rate(rows),
        sample_count=len(scores),
        confidence_interval=(
            bootstrap_confidence_interval(scores, level=confidence_level, iterations=bootstrap_iterations, seed=seed)
            if len(scores) >= 2
            else None
        ),
        dataset_refs=tuple(sorted({row.dataset_name for row in rows})),
    )


def _summarize_overall(
    model_id: str,
    rows: list[ScoredCase],
    weights: Mapping[str, Decimal],
    confidence_level: Decimal,
    bootstrap_iterations: int,
    seed: int,
) -> QualitySummary:
    """Build a model's weighted-overall summary across the tasks present in weights."""
    by_task: dict[str, list[ScoredCase]] = {}
    for scored in rows:
        by_task.setdefault(scored.case.task, []).append(scored)
    unweighted = sorted(set(by_task) - set(weights))
    if unweighted:
        raise BenchmarkError(f"tasks present but missing explicit weights: {', '.join(unweighted)}")

    task_means: dict[str, Decimal] = {}
    all_scores: list[Decimal] = []
    for task, task_rows in by_task.items():
        scores = [row.result.score for row in task_rows if row.result.score is not None]
        if not scores:
            continue
        task_means[task] = _mean(scores)
        all_scores.extend(scores)
    if not task_means:
        raise BenchmarkError(f"no scored cases available to summarize for model {model_id!r}")

    total_weight = sum((weights[task] for task in task_means), Decimal(0))
    if total_weight <= 0:
        raise BenchmarkError("sum of weights for tasks with scored cases must be positive")
    weighted_mean = sum((task_means[task] * weights[task] for task in task_means), Decimal(0)) / total_weight

    return QualitySummary(
        model_id=model_id,
        group_kind="overall",
        group_key=None,
        mean_score=weighted_mean,
        median_score=Decimal(str(statistics.median(all_scores))),
        pass_rate=_pass_rate(rows),
        sample_count=len(all_scores),
        confidence_interval=(
            bootstrap_confidence_interval(
                all_scores, level=confidence_level, iterations=bootstrap_iterations, seed=seed
            )
            if len(all_scores) >= 2
            else None
        ),
        dataset_refs=tuple(sorted({row.dataset_name for row in rows})),
    )


def _pass_rate(rows: list[ScoredCase]) -> Optional[Decimal]:
    """Return the fraction of rows with a recorded boolean pass verdict, if any."""
    verdicts = [row.result.metadata.get("passed") for row in rows if row.result.metadata.get("passed") is not None]
    if not verdicts:
        return None
    return Decimal(sum(1 for verdict in verdicts if verdict)) / Decimal(len(verdicts))


def _mean(values: Sequence[Decimal]) -> Decimal:
    """Return the arithmetic mean of a non-empty sequence of Decimals."""
    return sum(values, Decimal(0)) / Decimal(len(values))
