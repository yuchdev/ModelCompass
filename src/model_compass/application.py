"""Application facade — thin public entry point."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from model_compass.catalogs import CatalogService


@dataclass
class AnalyticsFacade:
    """Small public facade for application features."""

    catalog: CatalogService = field(default_factory=CatalogService)


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
