"""Empirical summaries of measured model executions."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from decimal import Decimal
from math import ceil
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict

from model_compass.domain import Observation


class LatencySummary(BaseModel):
    """Latency statistics with explicit denominators."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    latency_sample_count: int
    mean_latency_ms: Optional[Decimal]
    p50_latency_ms: Optional[Decimal]
    p95_latency_ms: Optional[Decimal]
    ttft_sample_count: int
    mean_time_to_first_token_ms: Optional[Decimal]


class ReliabilitySummary(BaseModel):
    """Success rate with sample count and minimum-evidence handling."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    success_count: int
    success_rate: Optional[Decimal]
    failure_categories: dict[str, int]


class CostSummary(BaseModel):
    """Actual and estimated costs kept separate in every aggregate."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    actual_cost_count: int
    total_actual_cost: Optional[Decimal]
    mean_actual_cost: Optional[Decimal]
    estimated_cost_count: int
    total_estimated_cost: Optional[Decimal]
    mean_estimated_cost: Optional[Decimal]
    cost_basis: Literal["actual", "estimated", "mixed", "none"]


class UsageSummary(BaseModel):
    """Average and total input/output token usage."""

    model_config = ConfigDict(frozen=True)

    sample_count: int
    input_token_sample_count: int
    total_input_tokens: Optional[int]
    average_input_tokens: Optional[Decimal]
    output_token_sample_count: int
    total_output_tokens: Optional[int]
    average_output_tokens: Optional[Decimal]


class ObservationSummary(BaseModel):
    """Combined empirical summary; each component carries its own sample counts."""

    model_config = ConfigDict(frozen=True)

    latency: LatencySummary
    reliability: ReliabilitySummary
    cost: CostSummary
    usage: UsageSummary
    sufficient_samples: bool


def summarize_observations(
    observations: Iterable[Observation],
    *,
    min_samples: int = 5,
) -> ObservationSummary:
    """Summarize observations using nearest-rank p50/p95 and exact Decimal means.

    The nearest-rank percentile is the sorted value at index ``ceil(p*n)-1``.
    Each metric's derived values are suppressed until at least ``min_samples``
    observations contain that measurement; its sample count remains visible.
    """
    if min_samples < 1:
        raise ValueError("min_samples must be at least one")
    rows = tuple(observations)
    enough = len(rows) >= min_samples

    latencies = [row.latency_ms for row in rows if row.latency_ms is not None]
    ttfts = [row.time_to_first_token_ms for row in rows if row.time_to_first_token_ms is not None]
    if len(latencies) >= min_samples:
        ordered_latency = sorted(latencies)
        mean_latency: Optional[Decimal] = _mean(latencies)
        p50: Optional[Decimal] = _nearest_rank(ordered_latency, 0.50)
        p95: Optional[Decimal] = _nearest_rank(ordered_latency, 0.95)
    else:
        mean_latency = None
        p50 = None
        p95 = None
    mean_ttft = _mean(ttfts) if len(ttfts) >= min_samples else None

    successes = sum(row.success for row in rows)
    failure_categories = Counter(row.failure_category for row in rows if not row.success and row.failure_category)
    reliability = ReliabilitySummary(
        sample_count=len(rows),
        success_count=successes,
        success_rate=(Decimal(successes) / Decimal(len(rows))) if enough and rows else None,
        failure_categories=dict(sorted(failure_categories.items())),
    )

    actual = [row.actual_cost for row in rows if row.actual_cost is not None]
    estimated = [row.estimated_cost for row in rows if row.estimated_cost is not None]
    cost_basis: Literal["actual", "estimated", "mixed", "none"]
    if actual and estimated:
        cost_basis = "mixed"
    elif actual:
        cost_basis = "actual"
    elif estimated:
        cost_basis = "estimated"
    else:
        cost_basis = "none"
    cost = CostSummary(
        sample_count=len(rows),
        actual_cost_count=len(actual),
        total_actual_cost=sum(actual, Decimal(0)) if len(actual) >= min_samples else None,
        mean_actual_cost=_mean(actual) if len(actual) >= min_samples else None,
        estimated_cost_count=len(estimated),
        total_estimated_cost=sum(estimated, Decimal(0)) if len(estimated) >= min_samples else None,
        mean_estimated_cost=_mean(estimated) if len(estimated) >= min_samples else None,
        cost_basis=cost_basis,
    )

    inputs = [row.input_tokens for row in rows if row.input_tokens is not None]
    outputs = [row.output_tokens for row in rows if row.output_tokens is not None]
    usage = UsageSummary(
        sample_count=len(rows),
        input_token_sample_count=len(inputs),
        total_input_tokens=sum(inputs) if len(inputs) >= min_samples else None,
        average_input_tokens=_mean_ints(inputs) if len(inputs) >= min_samples else None,
        output_token_sample_count=len(outputs),
        total_output_tokens=sum(outputs) if len(outputs) >= min_samples else None,
        average_output_tokens=_mean_ints(outputs) if len(outputs) >= min_samples else None,
    )

    return ObservationSummary(
        latency=LatencySummary(
            sample_count=len(rows),
            latency_sample_count=len(latencies),
            mean_latency_ms=mean_latency,
            p50_latency_ms=p50,
            p95_latency_ms=p95,
            ttft_sample_count=len(ttfts),
            mean_time_to_first_token_ms=mean_ttft,
        ),
        reliability=reliability,
        cost=cost,
        usage=usage,
        sufficient_samples=enough,
    )


def _mean(values: list[Decimal]) -> Decimal:
    """Return the arithmetic mean of a non-empty list of Decimals."""
    return sum(values, Decimal(0)) / Decimal(len(values))


def _mean_ints(values: list[int]) -> Decimal:
    """Return the arithmetic mean of a non-empty list of ints as a Decimal."""
    return Decimal(sum(values)) / Decimal(len(values))


def _nearest_rank(values: list[Decimal], quantile: float) -> Decimal:
    """Return the nearest-rank quantile of a sorted list of Decimals."""
    return values[max(0, ceil(quantile * len(values)) - 1)]
