from __future__ import annotations

import os
from decimal import Decimal

import pytest

from model_compass.catalogs.openrouter import OpenRouterCatalogAdapter


@pytest.mark.live
@pytest.mark.asyncio
async def test_openrouter_live_catalog_stable_properties():
    """[E2E] live catalog invariants: the real OpenRouter catalog has stable, well-typed fields.

    Scenario: Fetches the live catalog when opted in and checks identity and pricing invariants.
    Boundaries: Real OpenRouter HTTP endpoint; runs only when the live env flag is set.
    On failure, first check: live payload drift in model identity or pricing component types.
    """
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
