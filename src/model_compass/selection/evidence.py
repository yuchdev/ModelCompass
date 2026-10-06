"""Traceable metric evidence and quality-provider implementations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from decimal import Decimal
from typing import Generic, Optional, Protocol, TypeVar, Union

from pydantic import BaseModel, ConfigDict, Field

from model_compass.metrics.task_observations import QualityEvidence

T = TypeVar("T")


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
