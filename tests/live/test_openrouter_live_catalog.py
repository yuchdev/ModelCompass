from __future__ import annotations

import os
from decimal import Decimal

import pytest

from model_compass.catalogs.openrouter import OpenRouterCatalogAdapter


@pytest.mark.live
@pytest.mark.asyncio
async def test_openrouter_live_catalog_stable_properties() -> None:
    if os.getenv("MODEL_ANALYTICS_LIVE_OPENROUTER") != "1":
        pytest.skip("Set MODEL_ANALYTICS_LIVE_OPENROUTER=1 to run live OpenRouter catalog test")

    adapter = OpenRouterCatalogAdapter(api_key=os.getenv("OPENROUTER_API_KEY"))
    snapshot = await adapter.refresh(force=True)

    assert snapshot.models
    for profile in snapshot.models.values():
        assert profile.identity.model_id
        for component in profile.pricing.components.values():
            assert isinstance(component.amount, Decimal)
            assert component.amount >= Decimal("0")
