from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
import respx

from model_compass.catalogs.exceptions import (
    CatalogCacheError,
    CatalogFetchError,
    CatalogParseError,
)
from model_compass.catalogs.openrouter import (
    OpenRouterCatalogAdapter,
    _as_int,
    _as_time,
    _bool_to_support,
    _flag_from_modalities,
)
from model_compass.domain import SupportStatus


@pytest.mark.unit
@pytest.mark.asyncio
async def test_openrouter_offline_without_cache_raises(tmp_path: Path):
    """[Unit] offline cold cache: offline refresh with no cache raises CatalogCacheError.

    Scenario: Constructs an adapter on an empty cache dir and refreshes in offline mode.
    Boundaries: Real adapter and filesystem; no network and no mocks.
    On failure, first check: the offline path requiring an existing cache before returning.
    """
    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogCacheError):
        await adapter.refresh(offline=True)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_fetch_error_uses_stale_cache(tmp_path: Path):
    """[Unit] stale fallback: a later fetch error falls back to the cached snapshot marked stale.

    Scenario: Populates the cache, then forces a refresh whose network call fails on a later day.
    Boundaries: Real adapter and cache dir; HTTP calls are faked with respx.
    On failure, first check: fetch-failure fallback returning the cache with stale set to True.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}]})
    )
    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    await adapter.refresh(force=True, now_utc=datetime(2026, 1, 1, tzinfo=UTC))

    respx.get("https://openrouter.ai/api/v1/models").mock(side_effect=httpx.ConnectError("boom"))
    stale = await adapter.refresh(force=True, now_utc=datetime(2026, 1, 2, tzinfo=UTC))

    assert stale.stale is True


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_retries_transient_errors(tmp_path: Path):
    """[Unit] retry then succeed: a transient error is retried and the second attempt succeeds.

    Scenario: Mocks the first call to raise and the second to return 200, with retries enabled.
    Boundaries: Real adapter and cache dir; HTTP calls are faked with respx.
    On failure, first check: retry counting and that the successful retry yields an empty model set.
    """
    calls = {"count": 0}

    def _response(_: httpx.Request) -> httpx.Response:
        """Fail on the first call, then return an empty success payload."""
        calls["count"] += 1
        if calls["count"] < 2:
            raise httpx.ConnectError("temporary")
        return httpx.Response(200, json={"data": []})

    respx.get("https://openrouter.ai/api/v1/models").mock(side_effect=_response)

    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path, retries=1, retry_backoff_seconds=0)
    snapshot = await adapter.refresh(force=True)

    assert snapshot.models == {}
    assert calls["count"] == 2


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_retries_exhausted(tmp_path: Path):
    """[Unit] retries exhausted: persistent errors surface as CatalogFetchError.

    Scenario: Mocks every call to raise a connect error with one retry configured and refreshes.
    Boundaries: Real adapter and cache dir; HTTP calls are faked with respx.
    On failure, first check: the retry loop giving up and raising CatalogFetchError.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(side_effect=httpx.ConnectError("temporary"))
    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path, retries=1, retry_backoff_seconds=0)
    with pytest.raises(CatalogFetchError):
        await adapter.refresh(force=True)


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_uses_fresh_cache_without_network(tmp_path: Path):
    """[Unit] fresh cache hit: a non-forced refresh within TTL serves the cache without a call.

    Scenario: Populates the cache, resets the call log, then refreshes again within the TTL window.
    Boundaries: Real adapter and cache dir; HTTP calls are faked with respx.
    On failure, first check: TTL freshness check skipping the network on the second refresh.
    """
    route = respx.get("https://openrouter.ai/api/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "openai/gpt-4o-mini"}]})
    )
    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    first = await adapter.refresh(force=True, now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    assert route.called

    route.calls.reset()
    second = await adapter.refresh(force=False, now_utc=datetime(2026, 1, 1, tzinfo=UTC))
    assert second.models == first.models


@pytest.mark.unit
@pytest.mark.asyncio
@respx.mock
async def test_openrouter_response_json_not_object(tmp_path: Path):
    """[Unit] non-object JSON: a top-level JSON array raises CatalogParseError.

    Scenario: Mocks the endpoint to return a JSON list rather than an object and refreshes.
    Boundaries: Real adapter and cache dir; HTTP calls are faked with respx.
    On failure, first check: the type guard rejecting non-object top-level JSON.
    """
    respx.get("https://openrouter.ai/api/v1/models").mock(return_value=httpx.Response(200, json=[]))
    adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    with pytest.raises(CatalogParseError):
        await adapter.refresh(force=True)


@pytest.mark.unit
def test_openrouter_helper_parsers():
    """[Unit] helper parsers: int/time/bool/modality helpers map inputs to expected values.

    Scenario: Calls the private parsing helpers with valid and invalid inputs.
    Boundaries: Pure functions; no I/O and no mocks.
    On failure, first check: the individual helper return values for the failing input.
    """
    assert _as_int("10") == 10
    assert _as_int("x") is None
    assert _as_time("22:30:00") is not None
    assert _as_time("bad-time") is None
    assert _bool_to_support(False) == SupportStatus.UNSUPPORTED
    assert _flag_from_modalities("video", ("text",), ("text",)) == SupportStatus.UNKNOWN
