"""Privacy-conscious execution observations and task-specific summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from statistics import median
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.domain.models import parse_decimal


class Observation(BaseModel):
    """One execution outcome; request and message bodies are intentionally absent."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    endpoint_id: Optional[str] = None
    succeeded: bool
    latency_ms: int = Field(ge=0)
    actual_cost_usd: Optional[Decimal] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    quality_score: Optional[Decimal] = None
    evaluator_type: Optional[str] = None

    @field_validator("model_id", "task")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        """Reject blank model_id and task values."""
        if not value.strip():
            raise ValueError("model_id and task must not be empty")
        return value

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        """Require a timezone-aware timestamp and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("actual_cost_usd", "quality_score", mode="before")
    @classmethod
    def _decimal_values(cls, value: object) -> Optional[Decimal]:
        """Parse optional numeric fields into Decimals, preserving None."""
        if value is None:
            return None
        return parse_decimal(value)

    @field_validator("actual_cost_usd")
    @classmethod
    def _non_negative_cost(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        """Reject non-finite or negative actual cost values."""
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("actual_cost_usd must be non-negative")
        return value

    @field_validator("quality_score")
    @classmethod
    def _quality_range(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        """Reject optional quality scores outside the inclusive 0 to 1 range."""
        if value is not None and (not value.is_finite() or not Decimal("0") <= value <= Decimal("1")):
            raise ValueError("quality_score must be between 0 and 1")
        return value


class QualityEvidence(BaseModel):
    """Task-specific quality measurement with benchmark provenance."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    quality_score: Decimal
    sample_size: int = Field(ge=1)
    source: str
    evaluator_type: str
    dataset: Optional[str] = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("evaluated_at")
    @classmethod
    def _normalize_evaluated_at(cls, value: datetime) -> datetime:
        """Require a timezone-aware evaluation time and normalize it to UTC."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamps must include a timezone")
        return value.astimezone(UTC)

    @field_validator("quality_score", mode="before")
    @classmethod
    def _decimal_quality(cls, value: object) -> Decimal:
        """Parse the quality score into a Decimal."""
        return parse_decimal(value)

    @field_validator("quality_score")
    @classmethod
    def _quality_range(cls, value: Decimal) -> Decimal:
        """Reject quality scores outside the inclusive 0 to 1 range."""
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
            raise ValueError("quality_score must be between 0 and 1")
        return value


class MetricSummary(BaseModel):
    """Aggregate measurements for a model and exact task."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    sample_size: int
    success_count: int
    reliability: Decimal
    mean_latency_ms: Decimal
    median_latency_ms: Decimal
    p95_latency_ms: int
    mean_cost_usd: Optional[Decimal] = None
    mean_quality: Optional[Decimal] = None
    quality_sample_size: int = 0
    observed_at: Optional[datetime] = None
    quality_observed_at: Optional[datetime] = None


def summarize_observations(model_id: str, task: str, observations: list[Observation]) -> Optional[MetricSummary]:
    """Summarize observations without silently mixing task-specific evidence."""
    selected = [item for item in observations if item.model_id == model_id and item.task == task]
    if not selected:
        return None

    latencies = sorted(item.latency_ms for item in selected)
    costs = [item.actual_cost_usd for item in selected if item.actual_cost_usd is not None]
    qualities = [item.quality_score for item in selected if item.quality_score is not None]
    p95_index = max(0, (95 * len(latencies) + 99) // 100 - 1)
    n = Decimal(len(selected))
    success_count = sum(item.succeeded for item in selected)
    return MetricSummary(
        model_id=model_id,
        task=task,
        sample_size=len(selected),
        success_count=success_count,
        reliability=Decimal(success_count) / n,
        mean_latency_ms=Decimal(sum(latencies)) / n,
        median_latency_ms=Decimal(str(median(latencies))),
        p95_latency_ms=latencies[p95_index],
        mean_cost_usd=sum(costs, Decimal("0")) / len(costs) if costs else None,
        mean_quality=sum(qualities, Decimal("0")) / len(qualities) if qualities else None,
        quality_sample_size=len(qualities),
        observed_at=max(item.timestamp for item in selected),
        quality_observed_at=(
            max(item.timestamp for item in selected if item.quality_score is not None) if qualities else None
        ),
    )


def summarize_quality_evidence(
    model_id: str, task: str, evidence: list[QualityEvidence]
) -> Optional[tuple[Decimal, int]]:
    """Return sample-weighted quality from exact-task evidence only."""
    selected = [item for item in evidence if item.model_id == model_id and item.task == task]
    if not selected:
        return None
    samples = sum(item.sample_size for item in selected)
    weighted_score = sum((item.quality_score * item.sample_size for item in selected), Decimal("0"))
    return weighted_score / samples, samples
