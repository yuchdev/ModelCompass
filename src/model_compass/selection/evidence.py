"""Traceable metric evidence and quality-provider implementations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Generic, Optional, Protocol, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field

from model_compass.metrics.task_observations import QualityEvidence

T = TypeVar("T")


class QualityResolutionRule(StrEnum):
    """Which precedence rule selected a request's quality evidence."""

    EXACT_TASK_LOCAL_BENCHMARK = "exact_task_local_benchmark"
    EXACT_TASK_IMPORTED_BENCHMARK = "exact_task_imported_benchmark"
    BROADER_FALLBACK = "broader_fallback_evidence"


class MetricEvidence(BaseModel, Generic[T]):
    """A metric value with the provenance needed to interpret it."""

    model_config = ConfigDict(frozen=True)

    value: T
    source: str
    task: Optional[str] = None
    sample_count: Optional[int] = Field(default=None, ge=0)
    observed_at: Optional[datetime] = None
    confidence: Optional[Decimal] = None
    notes: tuple[str, ...] = ()
    resolution_rule: Optional[QualityResolutionRule] = None


class QualityProvider(Protocol):
    """Lookup interface for exact-task quality evidence."""

    def get_quality_evidence(self, model_id: str, task: str) -> Optional[MetricEvidence[Decimal]]:
        """Return quality evidence for a model and task, if available."""


class InMemoryQualityProvider:
    """Static quality evidence held in memory; performs no network access."""

    def __init__(
        self,
        evidence: Optional[
            Union[
                Mapping[str, MetricEvidence[Decimal]],
                Iterable[tuple[str, MetricEvidence[Decimal]]],
            ]
        ] = None,
    ):
        """Store the provided quality evidence as a model-indexed mapping."""
        self._evidence = dict(evidence or ())

    def get_quality_evidence(self, model_id: str, task: str) -> Optional[MetricEvidence[Decimal]]:
        """Return matching model and task evidence."""
        evidence = self._evidence.get(model_id)
        if evidence is None or evidence.task not in (None, task):
            return None
        return evidence


class BenchmarkQualityProvider:
    """Adapt persisted benchmark evidence to the reusable metric interface."""

    def __init__(self, evidence: Iterable[QualityEvidence] = ()):
        """Store the benchmark quality evidence records."""
        self._evidence = tuple(evidence)

    def get_quality_evidence(self, model_id: str, task: str) -> Optional[MetricEvidence[Decimal]]:
        """Return the sample-weighted score from exact-task benchmark evidence."""
        matches = [item for item in self._evidence if item.model_id == model_id and item.task == task]
        if not matches:
            return None
        count = sum(item.sample_size for item in matches)
        score = sum((item.quality_score * item.sample_size for item in matches), Decimal("0")) / count
        return MetricEvidence(
            value=score,
            source="benchmark",
            task=task,
            sample_count=count,
            observed_at=max(item.evaluated_at for item in matches),
            notes=tuple(sorted({f"{item.source}:{item.dataset or item.evaluator_type}" for item in matches})),
        )


def partition_quality_evidence(
    evidence: Iterable[QualityEvidence],
) -> tuple[tuple[QualityEvidence, ...], tuple[QualityEvidence, ...]]:
    """Split quality evidence into (local benchmark, imported) by its source convention.

    Evidence from a locally run benchmark uses `source == "benchmark"`; evidence
    brought in via `benchmarks.external_evidence.import_external_evidence` uses
    `source.startswith("imported:")`. Anything else is treated as local.
    """
    imported = tuple(item for item in evidence if item.source.startswith("imported:"))
    local = tuple(item for item in evidence if not item.source.startswith("imported:"))
    return local, imported


def resolve_quality_evidence(
    model_id: str,
    task: str,
    *,
    local_benchmark_evidence: Iterable[QualityEvidence] = (),
    imported_evidence: Iterable[QualityEvidence] = (),
    allow_fallback: bool = False,
) -> Optional[MetricEvidence[Decimal]]:
    """Resolve quality evidence for one request using an explicit precedence order.

    1. Exact-task evidence from a locally run benchmark.
    2. Exact-task evidence imported from an external source.
    3. Broader fallback evidence (any task, local and imported combined) -
       only considered when the caller explicitly opts in via `allow_fallback`.
    4. Otherwise `None`: the request's quality is unknown, never guessed.

    The returned evidence's `resolution_rule` records which tier was used.
    """
    local_exact = [item for item in local_benchmark_evidence if item.model_id == model_id and item.task == task]
    if local_exact:
        return _weighted_evidence(local_exact, rule=QualityResolutionRule.EXACT_TASK_LOCAL_BENCHMARK, task=task)

    imported_exact = [item for item in imported_evidence if item.model_id == model_id and item.task == task]
    if imported_exact:
        return _weighted_evidence(imported_exact, rule=QualityResolutionRule.EXACT_TASK_IMPORTED_BENCHMARK, task=task)

    if allow_fallback:
        broader = [item for item in (*local_benchmark_evidence, *imported_evidence) if item.model_id == model_id]
        if broader:
            return _weighted_evidence(broader, rule=QualityResolutionRule.BROADER_FALLBACK, task=None)

    return None


def _weighted_evidence(
    items: list[QualityEvidence],
    *,
    rule: QualityResolutionRule,
    task: Optional[str],
) -> MetricEvidence[Decimal]:
    """Combine same-rule evidence into one sample-weighted MetricEvidence."""
    count = sum(item.sample_size for item in items)
    score = sum((item.quality_score * item.sample_size for item in items), Decimal("0")) / count
    source = "benchmark_fallback" if rule == QualityResolutionRule.BROADER_FALLBACK else "benchmark"
    return MetricEvidence(
        value=score,
        source=source,
        task=task,
        sample_count=count,
        observed_at=max(item.evaluated_at for item in items),
        notes=tuple(sorted({f"{item.source}:{item.dataset or item.evaluator_type}" for item in items})),
        resolution_rule=rule,
    )


class TieredQualityProvider:
    """QualityProvider using the exact-local > exact-imported > fallback precedence."""

    def __init__(
        self,
        *,
        local_benchmark_evidence: Iterable[QualityEvidence] = (),
        imported_evidence: Iterable[QualityEvidence] = (),
        allow_fallback: bool = False,
    ):
        """Store local and imported evidence and whether broader fallback is allowed."""
        self._local = tuple(local_benchmark_evidence)
        self._imported = tuple(imported_evidence)
        self._allow_fallback = allow_fallback

    def get_quality_evidence(self, model_id: str, task: str) -> Optional[MetricEvidence[Decimal]]:
        """Resolve quality evidence for a model and task using the tiered precedence rules."""
        return resolve_quality_evidence(
            model_id,
            task,
            local_benchmark_evidence=self._local,
            imported_evidence=self._imported,
            allow_fallback=self._allow_fallback,
        )
