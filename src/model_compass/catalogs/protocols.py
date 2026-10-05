"""Catalog provider protocols."""

from __future__ import annotations

from datetime import datetime
from typing import Protocol

from model_compass.domain import CatalogSnapshot


class CatalogProvider(Protocol):
    """Provider protocol for refreshing catalog snapshots."""

    async def refresh(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        now_utc: datetime | None = None,
    ) -> CatalogSnapshot:
        """Refresh and return a catalog snapshot."""
