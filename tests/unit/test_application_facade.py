from __future__ import annotations

from datetime import datetime

import pytest

from model_compass.application import AnalyticsFacade, analytics
from model_compass.catalogs.service import CatalogService
from model_compass.domain import CatalogSnapshot


class FakeService(CatalogService):
    def __init__(self) -> None:
        self.calls = 0

    async def refresh_async(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        include_litellm: bool = True,
        now_utc: datetime | None = None,
    ) -> CatalogSnapshot:
        del force, offline, include_litellm, now_utc
        self.calls += 1
        raise RuntimeError("not needed")


@pytest.mark.unit
def test_lazy_analytics_proxy_exposes_catalog() -> None:
    assert hasattr(analytics, "catalog")


@pytest.mark.unit
def test_analytics_facade_can_inject_service() -> None:
    service = FakeService()
    facade = AnalyticsFacade(catalog=service)
    assert facade.catalog is service


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_sync_raises_in_running_loop() -> None:
    service = CatalogService()
    with pytest.raises(RuntimeError):
        service.refresh()
