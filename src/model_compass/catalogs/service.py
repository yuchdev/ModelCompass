"""Catalog orchestration and public service facade."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from model_compass.domain import CatalogSnapshot, CatalogSource, ModelProfile

from .litellm import LiteLLMCatalogAdapter
from .merge import merge_catalog_snapshots
from .openrouter import OpenRouterCatalogAdapter
from .protocols import CatalogProvider


class CatalogService:
    """Small application-facing facade over catalog providers."""

    def __init__(
        self,
        *,
        openrouter_provider: CatalogProvider | None = None,
        litellm_provider: CatalogProvider | None = None,
    ) -> None:
        self._openrouter_provider = openrouter_provider or OpenRouterCatalogAdapter()
        self._litellm_provider = litellm_provider or LiteLLMCatalogAdapter()
        self._snapshot: CatalogSnapshot | None = None

    async def refresh_async(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        include_litellm: bool = True,
        now_utc: datetime | None = None,
    ) -> CatalogSnapshot:
        """Refresh provider catalogs and merge into a unified snapshot."""
        clock = now_utc or datetime.now(UTC)

        openrouter_snapshot = await self._openrouter_provider.refresh(
            force=force,
            offline=offline,
            now_utc=clock,
        )

        if include_litellm:
            litellm_snapshot = await self._litellm_provider.refresh(
                force=force,
                offline=offline,
                now_utc=clock,
            )
            merge_result = merge_catalog_snapshots(
                openrouter_snapshot, litellm_snapshot, now_utc=clock
            )
            self._snapshot = merge_result.snapshot
        else:
            self._snapshot = openrouter_snapshot

        return self._snapshot

    def refresh(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        include_litellm: bool = True,
        now_utc: datetime | None = None,
    ) -> CatalogSnapshot:
        """Synchronous catalog refresh facade for application/CLI use."""
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            raise RuntimeError(
                "CatalogService.refresh() cannot be called from a running event loop; "
                "use refresh_async() instead."
            )

        return asyncio.run(
            self.refresh_async(
                force=force,
                offline=offline,
                include_litellm=include_litellm,
                now_utc=now_utc,
            )
        )

    def list(self) -> list[ModelProfile]:
        """List normalized model profiles sorted by canonical id."""
        snapshot = self._require_snapshot()
        return [snapshot.models[key] for key in sorted(snapshot.models.keys())]

    def get(self, model_id: str) -> ModelProfile | None:
        """Get model by canonical id or provider-local id."""
        snapshot = self._require_snapshot()
        lowered = model_id.strip().lower()
        direct = snapshot.models.get(lowered)
        if direct is not None:
            return direct

        for profile in snapshot.models.values():
            if profile.identity.model_id.lower() == lowered:
                return profile

        return None

    def sources(self) -> tuple[CatalogSource, ...]:
        """List snapshot source entries."""
        snapshot = self._require_snapshot()
        return snapshot.sources

    def _require_snapshot(self) -> CatalogSnapshot:
        if self._snapshot is None:
            self._snapshot = self.refresh()
        return self._snapshot
