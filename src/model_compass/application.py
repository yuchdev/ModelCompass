"""Application facade — thin public entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

from model_compass.benchmarks import BenchmarkReport
from model_compass.catalogs import CatalogService
from model_compass.config import default_paths
from model_compass.domain import ModelProfile, RequestProfile
from model_compass.execution import (
    CompletionRequest,
    ExecutionBackend,
    ExecutionError,
    ExecutionResult,
    LiteLLMBackend,
)
from model_compass.metrics import Observation, ObservationSummary
from model_compass.selection import (
    QualityProvider,
    RequestCostEstimate,
    SelectionConstraint,
    SelectionDataPolicy,
    SelectionPolicy,
    SelectionResult,
    estimate_request_cost,
    select_model,
)
from model_compass.storage import ObservationStoreProtocol, SQLiteObservationStore


@dataclass
class AnalyticsFacade:
    """Small public facade for application features."""

    catalog: CatalogService = field(default_factory=CatalogService)
    observation_store: ObservationStoreProtocol | None = None

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
    ) -> ObservationSummary:
        """Return empirical metrics using the injected storage protocol."""
        return self._observations().summarize_model(
            model_id,
            since=since,
            recent=recent,
            now_utc=now_utc,
            task=task,
            endpoint=endpoint,
            min_samples=min_samples,
        )

    def estimate_cost(
        self,
        profile: ModelProfile,
        request: RequestProfile,
        *,
        now_utc: datetime | None = None,
    ) -> RequestCostEstimate:
        """Estimate the Decimal cost for a request and model profile."""
        return estimate_request_cost(profile, request, now_utc=now_utc)

    def select(
        self,
        profiles: list[ModelProfile],
        request: RequestProfile,
        *,
        policy: SelectionPolicy = SelectionPolicy.BEST,
        objective: SelectionPolicy | str | None = None,
        missing_data: SelectionDataPolicy | None = None,
        quality_provider: QualityProvider | None = None,
        constraints: tuple[SelectionConstraint, ...] = (),
        min_quality: Decimal | None = None,
        max_cost_usd: Decimal | None = None,
        max_latency_ms: int | Decimal | None = None,
        min_reliability: Decimal | None = None,
        required_capabilities: tuple[str, ...] = (),
        minimum_context: int | None = None,
        allowed_model_ids: tuple[str, ...] = (),
        blocked_model_ids: tuple[str, ...] = (),
        allowed_gateways: tuple[str, ...] = (),
        blocked_gateways: tuple[str, ...] = (),
        allowed_providers: tuple[str, ...] = (),
        blocked_providers: tuple[str, ...] = (),
        raise_on_empty: bool = False,
        now_utc: datetime | None = None,
    ) -> SelectionResult:
        """Select a model using task-matched evidence and composable constraints."""
        task = request.task or "general"
        return select_model(
            profiles,
            request,
            policy=policy,
            objective=objective,
            observations=self._observations().list(task=task),
            quality_evidence=self._observations().list_quality_evidence(task=task),
            quality_provider=quality_provider,
            missing_data=missing_data,
            constraints=constraints,
            min_quality=min_quality,
            max_cost_usd=max_cost_usd,
            max_latency_ms=max_latency_ms,
            min_reliability=min_reliability,
            required_capabilities=required_capabilities,
            minimum_context=minimum_context,
            allowed_model_ids=allowed_model_ids,
            blocked_model_ids=blocked_model_ids,
            allowed_gateways=allowed_gateways,
            blocked_gateways=blocked_gateways,
            allowed_providers=allowed_providers,
            blocked_providers=blocked_providers,
            raise_on_empty=raise_on_empty,
            now_utc=now_utc,
        )

    def record_benchmark(self, report: BenchmarkReport) -> None:
        """Persist benchmark quality and provenance separately from execution outcomes."""
        self._observations().record_quality_evidence(report.to_quality_evidence())

    def record_observation(self, observation: Observation) -> None:
        """Persist one aggregate execution observation."""
        self._observations().record(observation)

    def list_observations(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> list[Observation]:
        """Return locally recorded aggregate observations."""
        return self._observations().list(model_id=model_id, task=task)

    async def execute(
        self,
        request: CompletionRequest,
        *,
        backend: ExecutionBackend | None = None,
    ) -> ExecutionResult:
        """Run a completion and persist only aggregate usage observations."""
        try:
            result = await (backend or LiteLLMBackend()).complete(request)
        except ExecutionError as exc:
            if exc.latency_ms is not None:
                self.record_observation(
                    Observation(
                        model_id=request.model_id,
                        task=request.task,
                        succeeded=False,
                        latency_ms=exc.latency_ms,
                    )
                )
            raise
        self.record_observation(result.to_observation())
        return result

    def _observations(self) -> ObservationStoreProtocol:
        if self.observation_store is None:
            self.observation_store = SQLiteObservationStore(
                default_paths().data_dir / "observations.sqlite3"
            )
        return self.observation_store


class _LazyAnalyticsFacade:
    """Lazily construct the default analytics facade."""

    def __init__(self) -> None:
        self._instance: AnalyticsFacade | None = None

    def _get(self) -> AnalyticsFacade:
        if self._instance is None:
            self._instance = AnalyticsFacade()
        return self._instance

    def __getattr__(self, item: str) -> Any:
        return getattr(self._get(), item)


analytics = _LazyAnalyticsFacade()

__all__ = ["AnalyticsFacade", "analytics"]
