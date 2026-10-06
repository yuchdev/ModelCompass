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
async def test_openrouter_successful_fetch(tmp_path: Path):
    """[Local] successful fetch: a 200 payload yields a snapshot with models.

    Scenario: Mocks the models endpoint with one entry and refreshes the adapter forcefully.
    Boundaries: Real adapter and cache dir; the HTTP call is faked with respx.
    On failure, first check: route invocation and snapshot population from the mocked payload.
    """
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
async def test_openrouter_timeout_error(tmp_path: Path):
    """[Local] timeout maps to fetch error: a connect timeout raises CatalogFetchError.

    Scenario: Mocks the endpoint to raise a connect timeout and forces a refresh.
    Boundaries: Real adapter and cache dir; the HTTP transport is faked with respx.
    On failure, first check: timeout handling translating into CatalogFetchError.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(side_effect=httpx.ConnectTimeout("boom"))

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogFetchError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status_code", [401, 403, 429, 500])
async def test_openrouter_http_errors(tmp_path: Path, status_code: int):
    """[Local] http errors map to fetch error: non-2xx statuses raise CatalogFetchError.

    Scenario: Mocks the endpoint to return each parametrized error status and forces a refresh.
    Boundaries: Real adapter and cache dir; the HTTP response is faked with respx.
    On failure, first check: status-code handling for 401/403/429/500 raising CatalogFetchError.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(status_code, json={}))

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogFetchError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_malformed_json(tmp_path: Path):
    """[Local] non-JSON body: an unparseable response raises CatalogParseError.

    Scenario: Mocks the endpoint to return a 200 with a non-JSON body and forces a refresh.
    Boundaries: Real adapter and cache dir; the HTTP response is faked with respx.
    On failure, first check: JSON decoding guard translating into CatalogParseError.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, text="not-json"))

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogParseError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_top_level_malformed_schema(tmp_path: Path):
    """[Local] wrong top-level shape: a payload missing 'data' raises CatalogParseError.

    Scenario: Mocks the endpoint to return a JSON object without the expected data key.
    Boundaries: Real adapter and cache dir; the HTTP response is faked with respx.
    On failure, first check: top-level schema validation translating into CatalogParseError.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json={"models": []}))

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogParseError):
        await adapter.refresh(force=True)


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_skips_one_malformed_model_entry(tmp_path: Path):
    """[Local] partial payload: one bad entry is skipped and recorded as a parse warning.

    Scenario: Mocks a payload with one valid and one malformed model entry and refreshes.
    Boundaries: Real adapter and cache dir; the HTTP response is faked with respx.
    On failure, first check: per-entry resilience keeping valid models and emitting parse warnings.
    """
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
async def test_openrouter_authorization_header_optional(tmp_path: Path):
    """[Local] optional auth header: the bearer header is sent only when an api key is set.

    Scenario: Refreshes once without an api key and once with one, inspecting the request headers.
    Boundaries: Real adapter and cache dir; the HTTP call is captured via respx.
    On failure, first check: conditional Authorization header construction from the api key.
    """
    route = respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json={"data": []}))

    adapter_without_key = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    await adapter_without_key.refresh(force=True)
    assert "Authorization" not in route.calls[-1].request.headers

    adapter_with_key = OpenRouterCatalogAdapter(cache_dir=tmp_path, api_key="secret-value")
    await adapter_with_key.refresh(force=True)
    assert route.calls[-1].request.headers["Authorization"].startswith("Bearer ")


@pytest.mark.mock
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_errors_do_not_leak_api_key(tmp_path: Path):
    """[Local] no key leakage: a network error message never contains the api key.

    Scenario: Mocks a connect error on refresh with an api key set and inspects the raised error.
    Boundaries: Real adapter and cache dir; the HTTP transport is faked with respx.
    On failure, first check: error message construction accidentally embedding the api key.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(side_effect=httpx.ConnectError("network down"))

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path, api_key="very-secret")
    with pytest.raises(CatalogFetchError) as exc_info:
        await adapter.refresh(force=True)

    assert "very-secret" not in str(exc_info.value)
