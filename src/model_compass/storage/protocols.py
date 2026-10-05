"""Storage protocols used by application and analytics code."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol

from model_compass.domain import BenchmarkResult, BenchmarkRun, Observation, QualityEvidence
from model_compass.metrics.observations import ObservationSummary


class ObservationStore(Protocol):
    """Backend-independent access to persistent or in-memory analytics data."""

    def record_observation(
        self, observation: Observation, *, deduplicate: bool = False
    ) -> Observation: ...  # pragma: no branch

    def record_observations(
        self, observations: list[Observation], *, deduplicate: bool = False
    ) -> int: ...  # pragma: no branch

    def query_observations(
        self,
        *,
        model_id: str | None = None,
        task: str | None = None,
        endpoint: str | None = None,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        limit: int | None = None,
    ) -> list[Observation]: ...  # pragma: no branch

    def summarize_model(
        self,
        model_id: str,
        *,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        task: str | None = None,
        endpoint: str | None = None,
        min_samples: int = 5,
    ) -> ObservationSummary: ...  # pragma: no branch

    def summarize_task(
        self,
        task: str,
        *,
        model_id: str | None = None,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        endpoint: str | None = None,
        min_samples: int = 5,
    ) -> ObservationSummary: ...  # pragma: no branch

    def record_benchmark_run(self, run: BenchmarkRun) -> BenchmarkRun: ...  # pragma: no branch

    def query_benchmark_runs(self) -> list[BenchmarkRun]: ...  # pragma: no branch

    def record_benchmark_result(
        self, result: BenchmarkResult
    ) -> BenchmarkResult: ...  # pragma: no branch

    def query_benchmark_results(
        self, *, run_id: str | None = None
    ) -> list[BenchmarkResult]: ...  # pragma: no branch

    def record_quality_evidence(
        self, evidence: QualityEvidence
    ) -> QualityEvidence: ...  # pragma: no branch

    def query_quality_evidence(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> list[QualityEvidence]: ...  # pragma: no branch

    def delete_before(self, timestamp: datetime) -> int: ...  # pragma: no branch

    def vacuum(self) -> None: ...  # pragma: no branch

    def export_jsonl(self) -> str: ...  # pragma: no branch

    def import_jsonl(
        self, content: str, *, deduplicate: bool = False
    ) -> int: ...  # pragma: no branch
