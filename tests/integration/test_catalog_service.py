from __future__ import annotations

import sys
import types
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
import pytest
import respx

from model_compass.catalogs import CatalogService
from model_compass.catalogs.exceptions import CatalogCacheError
from model_compass.catalogs.litellm import LiteLLMCatalogAdapter
from model_compass.catalogs.openrouter import OpenRouterCatalogAdapter


@pytest.mark.integration
@pytest.mark.asyncio
@respx.mock
async def test_refresh_cache_offline_list_models(tmp_path: Path):
    """[Integration] cache then offline: a populated cache lets an offline refresh list models.

    Scenario: Refreshes online to warm the cache, then refreshes offline and lists the models.
    Boundaries: Real CatalogService, adapters and cache dir; the HTTP call is faked with respx.
    On failure, first check: the offline path reusing the on-disk cache written by the first refresh.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "openai/gpt-4o-mini", "pricing": {"prompt": "0.1"}}]},
        )
    )

    openrouter = OpenRouterCatalogAdapter(cache_dir=tmp_path, ttl=timedelta(minutes=5))
    service = CatalogService(openrouter_provider=openrouter, litellm_provider=LiteLLMCatalogAdapter())

    await service.refresh_async(force=True, include_litellm=False, now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    offline_snapshot = await service.refresh_async(offline=True, include_litellm=False)

    assert offline_snapshot.models
    assert service.list()


@pytest.mark.integration
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_and_litellm_merge(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """[Integration] cross-source merge: OpenRouter pricing and LiteLLM context combine per model.

    Scenario: Mocks OpenRouter and a fake litellm module, then refreshes with litellm included.
    Boundaries: Real CatalogService and adapters; HTTP via respx and litellm via a module fake.
    On failure, first check: merge precedence keeping OpenRouter price while adding litellm context.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "openai/gpt-4o-mini",
                        "supports_tools": None,
                        "pricing": {"prompt": "1"},
                    }
                ]
            },
        )
    )

    fake_litellm = types.SimpleNamespace(
        model_cost={
            "openrouter/openai/gpt-4o-mini": {
                "prompt_cost_per_token": "2",
                "max_input_tokens": 1000,
            }
        }
    )
    monkeypatch.setitem(sys.modules, "litellm", fake_litellm)

    service = CatalogService(openrouter_provider=OpenRouterCatalogAdapter(cache_dir=tmp_path))
    snapshot = await service.refresh_async(force=True, include_litellm=True)

    profile = snapshot.models["openrouter:openai/gpt-4o-mini"]
    assert profile.pricing.components["prompt"].amount == 1
    assert profile.capabilities.context_length == 1000


@pytest.mark.integration
@pytest.mark.asyncio
@respx.mock
async def test_stale_cache_marked(tmp_path: Path):
    """[Integration] stale marking: an offline refresh past the TTL returns a stale-flagged snapshot.

    Scenario: Warms the cache, then refreshes offline after the short TTL has elapsed.
    Boundaries: Real adapter and cache dir; the HTTP call is faked with respx and time is injected.
    On failure, first check: TTL expiry logic setting the stale flag on the returned snapshot.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}]})
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path, ttl=timedelta(seconds=1))
    await adapter.refresh(force=True, now_utc=datetime(2026, 1, 1, tzinfo=UTC))

    stale = await adapter.refresh(offline=True, now_utc=datetime(2026, 1, 1, 0, 0, 2, tzinfo=UTC))
    assert stale.stale is True


@pytest.mark.integration
@pytest.mark.asyncio
async def test_corrupt_cache_behavior(tmp_path: Path):
    """[Integration] corrupt cache: offline refresh raises while online load returns None.

    Scenario: Writes a corrupt cache file, then exercises offline refresh and the online load path.
    Boundaries: Real adapter and cache dir on the temp filesystem; no network.
    On failure, first check: corrupt-cache handling raising offline and returning None when online.
    """
    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    cache_file = tmp_path / "openrouter_catalog.json"
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text("{not-json", encoding="utf-8")

    with pytest.raises(CatalogCacheError):
        await adapter.refresh(offline=True)

    # Online mode ignores corrupt cache and would refresh when network is available.
    # Here we only validate corrupt-cache handling does not crash _load_cache path.
    assert adapter._load_cache(offline=False) is None
