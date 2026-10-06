"""Storage protocols used by application and analytics code."""

from __future__ import annotations

import builtins
from datetime import datetime, timedelta
from typing import Optional, Protocol, Union

from model_compass.domain import BenchmarkResult, BenchmarkRun, Observation, QualityEvidence
from model_compass.metrics.observations import ObservationSummary
from model_compass.metrics.task_observations import (
    Observation as TaskObservation,
)
from model_compass.metrics.task_observations import (
    QualityEvidence as TaskQualityEvidence,
)


class ObservationStore(Protocol):
    """Backend-independent access to persistent or in-memory analytics data."""

    def record_observation(self, observation: Observation, *, deduplicate: bool = False) -> Observation:
        """Record one observation and return its stored representation."""
        ...  # pragma: no branch

    def record_observations(self, observations: builtins.list[Observation], *, deduplicate: bool = False) -> int:
        """Record many observations and return the number stored."""
        ...  # pragma: no branch

    def record(self, observation: TaskObservation):
        """Store a task-selection observation."""
        ...  # pragma: no branch

    def list(self, *, model_id: Optional[str] = None, task: Optional[str] = None) -> builtins.list[TaskObservation]:
        """Return task-selection observations, optionally filtered."""
        ...  # pragma: no branch

    def query_observations(
        self,
        *,
        model_id: Optional[str] = None,
        task: Optional[str] = None,
        endpoint: Optional[str] = None,
        since: Optional[datetime] = None,
        recent: Optional[timedelta] = None,
        now_utc: Optional[datetime] = None,
        limit: Optional[int] = None,
    ) -> builtins.list[Observation]:
        """Return observations matching the given filters."""
        ...  # pragma: no branch

    def summarize_model(
        self,
        model_id: str,
        *,
        since: Optional[datetime] = None,
        recent: Optional[timedelta] = None,
        now_utc: Optional[datetime] = None,
        task: Optional[str] = None,
        endpoint: Optional[str] = None,
        min_samples: int = 5,
    ) -> ObservationSummary:
        """Summarize recorded observations for one model."""
        ...  # pragma: no branch

    def summarize_task(
        self,
        task: str,
        *,
        model_id: Optional[str] = None,
        since: Optional[datetime] = None,
        recent: Optional[timedelta] = None,
        now_utc: Optional[datetime] = None,
        endpoint: Optional[str] = None,
        min_samples: int = 5,
    ) -> ObservationSummary:
        """Summarize recorded observations for one task."""
        ...  # pragma: no branch

    def record_benchmark_run(self, run: BenchmarkRun) -> BenchmarkRun:
        """Record a benchmark run and return it."""
        ...  # pragma: no branch

    def query_benchmark_runs(self) -> builtins.list[BenchmarkRun]:
        """Return all recorded benchmark runs."""
        ...  # pragma: no branch

    def record_benchmark_result(self, result: BenchmarkResult) -> BenchmarkResult:
        """Record a benchmark result and return it."""
        ...  # pragma: no branch

    def query_benchmark_results(self, *, run_id: Optional[str] = None) -> builtins.list[BenchmarkResult]:
        """Return benchmark results, optionally filtered by run."""
        ...  # pragma: no branch

    def record_quality_evidence(
        self, evidence: Union[QualityEvidence, TaskQualityEvidence]
    ) -> Union[QualityEvidence, TaskQualityEvidence]:
        """Record quality evidence and return the stored value."""
        ...  # pragma: no branch

    def query_quality_evidence(
        self, *, model_id: Optional[str] = None, task: Optional[str] = None
    ) -> builtins.list[QualityEvidence]:
        """Return quality evidence matching the given filters."""
        ...  # pragma: no branch

    def list_quality_evidence(
        self, *, model_id: Optional[str] = None, task: Optional[str] = None
    ) -> builtins.list[TaskQualityEvidence]:
        """Return quality evidence in the task-selection shape."""
        ...  # pragma: no branch

    def delete_before(self, timestamp: datetime) -> int:
        """Delete observations recorded before the timestamp."""
        ...  # pragma: no branch

    def vacuum(self):
        """Reclaim unused storage space where supported."""
        ...  # pragma: no branch

    def export_jsonl(self) -> str:
        """Export all records as JSONL text."""
        ...  # pragma: no branch

    def import_jsonl(self, content: str, *, deduplicate: bool = False) -> int:
        """Import records from JSONL text and return the number imported."""
        ...  # pragma: no branch
