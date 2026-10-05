from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from model_compass.catalogs.exceptions import CatalogFetchError, CatalogParseError
from model_compass.catalogs.openrouter import OpenRouterCatalogAdapter


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_successful_fetch(tmp_path: Path) -> None:
    route = respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "openai/gpt-4o-mini",
                        "pricing": {"prompt": "0.1", "completion": "0.2"},
                    }
                ]
            },
        )
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    snapshot = await adapter.refresh(force=True, now_utc=datetime(2026, 1, 1, tzinfo=UTC))

    assert route.called
    assert snapshot.models


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_timeout_error(tmp_path: Path) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(side_effect=httpx.ConnectTimeout("boom"))

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogFetchError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
async def test_openrouter_http_errors(tmp_path: Path, status_code: int) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(status_code, json={})
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogFetchError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_malformed_json(tmp_path: Path) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, text="not-json")
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogParseError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_top_level_malformed_schema(tmp_path: Path) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"models": []})
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogParseError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_skips_one_malformed_model_entry(tmp_path: Path) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(
            200,
            json={"data": [{"id": "ok/model", "pricing": {"prompt": "1"}}, {"name": "broken"}]},
        )
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    snapshot = await adapter.refresh(force=True)

    assert len(snapshot.models) == 1
    assert snapshot.parse_warnings


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_authorization_header_optional(tmp_path: Path) -> None:
    route = respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": []})
    )

    adapter_without_key = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    await adapter_without_key.refresh(force=True)
    assert "Authorization" not in route.calls[-1].request.headers

    adapter_with_key = OpenRouterCatalogAdapter(cache_dir=tmp_path, api_key="secret-value")
    await adapter_with_key.refresh(force=True)
    assert route.calls[-1].request.headers["Authorization"].startswith("Bearer ")


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_errors_do_not_leak_api_key(tmp_path: Path) -> None:
    respx.get("https://openrouter.ai/api/v1/models").mock(
        side_effect=httpx.ConnectError("network down")
    )

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path, api_key="very-secret")
    with pytest.raises(CatalogFetchError) as exc_info:
        await adapter.refresh(force=True)

    assert "very-secret" not in str(exc_info.value)
