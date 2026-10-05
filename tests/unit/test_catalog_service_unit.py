from __future__ import annotations

from datetime import UTC, datetime

import pytest

from model_compass.catalogs.service import CatalogService
from model_compass.domain import (
    CatalogSnapshot,
    CatalogSource,
    ModelIdentity,
    ModelProfile,
    Pricing,
)


class FakeProvider:
    def __init__(self, snapshot: CatalogSnapshot) -> None:
        self.snapshot = snapshot

    async def refresh(
        self, *, force: bool = False, offline: bool = False, now_utc: datetime | None = None
    ) -> CatalogSnapshot:
        del force, offline, now_utc
        return self.snapshot


def _snapshot(name: str, model_id: str) -> CatalogSnapshot:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    profile = ModelProfile(
        identity=ModelIdentity(provider=name, model_id=model_id, canonical_id=f"{name}:{model_id}"),
        pricing=Pricing(),
        sources=(CatalogSource(name=name, retrieved_at=now, authoritative=name == "openrouter"),),
        retrieved_at=now,
    )
    return CatalogSnapshot(
        models={profile.identity.canonical_id: profile},
        sources=profile.sources,
        retrieved_at=now,
    )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_service_refresh_async_without_litellm() -> None:
    openrouter_snapshot = _snapshot("openrouter", "x")
    service = CatalogService(
        openrouter_provider=FakeProvider(openrouter_snapshot),
        litellm_provider=FakeProvider(_snapshot("litellm", "y")),
    )

    snapshot = await service.refresh_async(include_litellm=False)
    assert snapshot.models == openrouter_snapshot.models


@pytest.mark.unit
def test_service_refresh_sync_list_get_sources() -> None:
    openrouter_snapshot = _snapshot("openrouter", "x")
    service = CatalogService(
        openrouter_provider=FakeProvider(openrouter_snapshot),
        litellm_provider=FakeProvider(_snapshot("litellm", "y")),
    )

    refreshed = service.refresh(include_litellm=False)
    assert refreshed.models
    assert service.list()
    assert service.get("openrouter:x") is not None
    assert service.get("x") is not None
    assert service.get("does-not-exist") is None
    assert service.sources()
