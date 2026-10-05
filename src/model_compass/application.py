"""Application facade — thin public entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from model_compass.catalogs import CatalogService
from model_compass.metrics import ObservationSummary
from model_compass.storage import ObservationStore, SQLiteObservationStore


@dataclass
class AnalyticsFacade:
    """Small public facade for application features."""

    catalog: CatalogService = field(default_factory=CatalogService)
    observation_store: ObservationStore = field(default_factory=SQLiteObservationStore)

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
        return self.observation_store.summarize_model(
            model_id,
            since=since,
            recent=recent,
            now_utc=now_utc,
            task=task,
            endpoint=endpoint,
            min_samples=min_samples,
        )


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
