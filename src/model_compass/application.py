"""Application facade — thin public entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from model_compass.catalogs import CatalogService
from model_compass.config import default_paths
from model_compass.domain import MissingDataPolicy, ModelProfile, RequestProfile
from model_compass.metrics import Observation
from model_compass.selection import (
    CostEstimate,
    SelectionPolicy,
    SelectionResult,
    estimate_cost,
    select_model,
)
from model_compass.storage import ObservationStore


@dataclass
class AnalyticsFacade:
    """Small public facade for application features."""

    catalog: CatalogService = field(default_factory=CatalogService)
    observation_store: ObservationStore | None = None

    def estimate_cost(self, profile: ModelProfile, request: RequestProfile) -> CostEstimate:
        """Estimate the Decimal cost for a request and model profile."""
        return estimate_cost(profile, request)

    def select(
        self,
        profiles: list[ModelProfile],
        request: RequestProfile,
        *,
        policy: SelectionPolicy = SelectionPolicy.BEST,
        missing_data: MissingDataPolicy | None = None,
    ) -> SelectionResult:
        """Select a model using task-matched local observations."""
        return select_model(
            profiles,
            request,
            policy=policy,
            observations=self._observations().list(task=request.task),
            missing_data=missing_data,
        )

    def record_observation(self, observation: Observation) -> None:
        """Persist one aggregate execution observation."""
        self._observations().record(observation)

    def _observations(self) -> ObservationStore:
        if self.observation_store is None:
            self.observation_store = ObservationStore(
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
