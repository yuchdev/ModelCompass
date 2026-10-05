"""Token, request-cost, and empirical observation metrics."""

from collections.abc import Iterable
from typing import overload

from model_compass.domain import Observation as StoredObservation
from model_compass.metrics.costs import CostComponentEstimate, CostEstimate, estimate_cost
from model_compass.metrics.observations import (
    CostSummary,
    LatencySummary,
    ObservationSummary,
    ReliabilitySummary,
    UsageSummary,
)
from model_compass.metrics.observations import (
    summarize_observations as summarize_empirical_observations,
)
from model_compass.metrics.task_observations import (
    MetricSummary,
    Observation,
    QualityEvidence,
    summarize_quality_evidence,
)
from model_compass.metrics.task_observations import (
    summarize_observations as summarize_task_observations,
)
from model_compass.metrics.tokens import (
    FallbackTokenEstimator,
    LiteLLMTokenEstimator,
    TokenEstimate,
    TokenEstimator,
)


@overload
def summarize_observations(
    data: Iterable[StoredObservation], *, min_samples: int = 5
) -> ObservationSummary: ...


@overload
def summarize_observations(
    data: str, task: str, observations: list[Observation]
) -> MetricSummary | None: ...


def summarize_observations(
    data: Iterable[StoredObservation] | str,
    task: str | None = None,
    observations: list[Observation] | None = None,
    *,
    min_samples: int = 5,
) -> ObservationSummary | MetricSummary | None:
    """Summarize persisted records or exact-task selection observations."""
    if isinstance(data, str):
        if task is None or observations is None:
            raise TypeError("model_id, task, and observations are required")
        return summarize_task_observations(data, task, observations)
    if task is not None or observations is not None:
        raise TypeError("task summaries require a model_id, task, and observations")
    return summarize_empirical_observations(data, min_samples=min_samples)


__all__ = [
    "CostComponentEstimate",
    "CostEstimate",
    "CostSummary",
    "FallbackTokenEstimator",
    "LatencySummary",
    "LiteLLMTokenEstimator",
    "MetricSummary",
    "Observation",
    "ObservationSummary",
    "QualityEvidence",
    "ReliabilitySummary",
    "TokenEstimate",
    "TokenEstimator",
    "UsageSummary",
    "estimate_cost",
    "summarize_observations",
    "summarize_quality_evidence",
]
