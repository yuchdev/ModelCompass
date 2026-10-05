"""Privacy-conscious execution observations and task-specific summaries."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from statistics import median

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.domain.models import parse_decimal


class Observation(BaseModel):
    """One execution outcome; request and message bodies are intentionally absent."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    endpoint_id: str | None = None
    succeeded: bool
    latency_ms: int = Field(ge=0)
    actual_cost_usd: Decimal | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    quality_score: Decimal | None = None
    evaluator_type: str | None = None

    @field_validator("model_id", "task")
    @classmethod
    def _non_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("model_id and task must not be empty")
        return value

    @field_validator("actual_cost_usd", "quality_score", mode="before")
    @classmethod
    def _decimal_values(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return parse_decimal(value)

    @field_validator("actual_cost_usd")
    @classmethod
    def _non_negative_cost(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("actual_cost_usd must be non-negative")
        return value

    @field_validator("quality_score")
    @classmethod
    def _quality_range(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (
            not value.is_finite() or not Decimal("0") <= value <= Decimal("1")
        ):
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
    dataset: str | None = None
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @field_validator("quality_score", mode="before")
    @classmethod
    def _decimal_quality(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("quality_score")
    @classmethod
    def _quality_range(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
            raise ValueError("quality_score must be between 0 and 1")
        return value


class MetricSummary(BaseModel):
    """Aggregate measurements for a model and exact task."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    sample_size: int
    reliability: Decimal
    mean_latency_ms: Decimal
    median_latency_ms: Decimal
    p95_latency_ms: int
    mean_cost_usd: Decimal | None = None
    mean_quality: Decimal | None = None
    observed_at: datetime | None = None


def summarize_observations(
    model_id: str, task: str, observations: list[Observation]
) -> MetricSummary | None:
    """Summarize observations without silently mixing task-specific evidence."""
    selected = [item for item in observations if item.model_id == model_id and item.task == task]
    if not selected:
        return None

    latencies = sorted(item.latency_ms for item in selected)
    costs = [item.actual_cost_usd for item in selected if item.actual_cost_usd is not None]
    qualities = [item.quality_score for item in selected if item.quality_score is not None]
    p95_index = max(0, (95 * len(latencies) + 99) // 100 - 1)
    n = Decimal(len(selected))
    return MetricSummary(
        model_id=model_id,
        task=task,
        sample_size=len(selected),
        reliability=Decimal(sum(item.succeeded for item in selected)) / n,
        mean_latency_ms=Decimal(sum(latencies)) / n,
        median_latency_ms=Decimal(str(median(latencies))),
        p95_latency_ms=latencies[p95_index],
        mean_cost_usd=sum(costs, Decimal("0")) / len(costs) if costs else None,
        mean_quality=sum(qualities, Decimal("0")) / len(qualities) if qualities else None,
        observed_at=max(item.timestamp for item in selected),
    )


def summarize_quality_evidence(
    model_id: str, task: str, evidence: list[QualityEvidence]
) -> tuple[Decimal, int] | None:
    """Return sample-weighted quality from exact-task evidence only."""
    selected = [item for item in evidence if item.model_id == model_id and item.task == task]
    if not selected:
        return None
    samples = sum(item.sample_size for item in selected)
    weighted_score = sum((item.quality_score * item.sample_size for item in selected), Decimal("0"))
    return weighted_score / samples, samples
