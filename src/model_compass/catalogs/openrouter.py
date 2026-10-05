"""OpenRouter catalog adapter with raw snapshot cache."""

from __future__ import annotations

import asyncio
import json
import tempfile
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any

import httpx

from model_compass import __version__
from model_compass.config import default_paths
from model_compass.domain import (
    KNOWN_OPENROUTER_PRICE_KEYS,
    CatalogSnapshot,
    CatalogSource,
    ModelCapabilities,
    ModelEndpoint,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    PricingOverride,
    PricingProvenance,
    SupportStatus,
    canonical_model_id,
)

from .exceptions import CatalogCacheError, CatalogFetchError, CatalogParseError

_CACHE_VERSION = 1
_DEFAULT_BASE_URL = "https://openrouter.ai"
_DEFAULT_TIMEOUT = httpx.Timeout(connect=5.0, read=15.0, write=10.0, pool=5.0)


class OpenRouterCatalogAdapter:
    """Fetch and normalize OpenRouter model catalog."""

    def __init__(
        self,
        *,
        base_url: str = _DEFAULT_BASE_URL,
        api_key: str | None = None,
        timeout: httpx.Timeout = _DEFAULT_TIMEOUT,
        cache_dir: Path | None = None,
        ttl: timedelta = timedelta(hours=6),
        retries: int = 0,
        retry_backoff_seconds: float = 0.25,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout
        self._cache_dir = cache_dir or default_paths().cache_dir / "catalog"
        self._ttl = ttl
        self._retries = retries
        self._retry_backoff_seconds = retry_backoff_seconds
        self._client = client

    async def refresh(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        now_utc: datetime | None = None,
    ) -> CatalogSnapshot:
        """Refresh from OpenRouter or cache."""
        clock = now_utc or datetime.now(UTC)
        cache = self._load_cache(offline=offline)

        if offline:
            if cache is None:
                raise CatalogCacheError("offline mode enabled but no cache snapshot is available")
            return _mark_stale_if_needed(cache, now=clock, ttl=self._ttl)

        if (
            not force
            and cache is not None
            and not _is_expired(cache.retrieved_at, now=clock, ttl=self._ttl)
        ):
            return cache

        try:
            raw_payload = await self._fetch_models()
            snapshot = self._parse_payload(raw_payload, clock=clock)
            self._write_cache(snapshot=snapshot, raw_payload=raw_payload)
        except (CatalogFetchError, CatalogParseError):
            if cache is None:
                raise
            stale_cache = cache.model_copy(update={"stale": True})
            return stale_cache
        else:
            return snapshot

    async def _fetch_models(self) -> dict[str, Any]:
        url = f"{self._base_url}/api/v1/models"
        headers = {
            "User-Agent": f"model-compass/{__version__}",
            "Accept": "application/json",
        }
        if self._api_key:
            headers["Authorization"] = "Bearer " + self._api_key

        attempts = self._retries + 1
        last_exc: Exception | None = None

        for attempt in range(attempts):
            try:
                if self._client is not None:
                    response = await self._client.get(url, headers=headers, timeout=self._timeout)
                else:
                    async with httpx.AsyncClient() as client:
                        response = await client.get(url, headers=headers, timeout=self._timeout)
            except (httpx.TimeoutException, httpx.NetworkError) as exc:
                last_exc = exc
                if attempt < attempts - 1:
                    await asyncio.sleep(self._retry_backoff_seconds * (attempt + 1))
                    continue
                break

            if response.status_code in {401, 403}:
                raise CatalogFetchError(
                    f"OpenRouter returned HTTP {response.status_code} for catalog request"
                )
            if response.status_code == 429:
                raise CatalogFetchError("OpenRouter rate limited catalog request (HTTP 429)")
            if response.status_code >= 500:
                raise CatalogFetchError(
                    f"OpenRouter server error during catalog request: HTTP {response.status_code}"
                )
            if response.status_code >= 400:
                raise CatalogFetchError(
                    f"OpenRouter catalog request failed: HTTP {response.status_code}"
                )

            try:
                payload = response.json()
            except ValueError as exc:
                raise CatalogParseError("OpenRouter catalog response is not valid JSON") from exc

            if not isinstance(payload, dict):
                raise CatalogParseError("OpenRouter catalog response must be a JSON object")
            return payload

        if last_exc is not None:
            raise CatalogFetchError(f"failed to fetch OpenRouter catalog from {url}") from last_exc
        raise CatalogFetchError("failed to fetch OpenRouter catalog")

    def _parse_payload(self, payload: dict[str, Any], *, clock: datetime) -> CatalogSnapshot:
        data = payload.get("data")
        if not isinstance(data, list):
            raise CatalogParseError("OpenRouter catalog top-level 'data' must be a list")

        models: dict[str, ModelProfile] = {}
        parse_warnings: list[str] = []

        for index, item in enumerate(data):
            if not isinstance(item, dict):
                parse_warnings.append(f"skipped model at index {index}: entry is not an object")
                continue
            try:
                profile = self._parse_model(item, clock=clock)
            except (KeyError, ValueError, TypeError) as exc:
                parse_warnings.append(f"skipped model at index {index}: {exc}")
                continue
            models[profile.identity.canonical_id] = profile

        source = CatalogSource(
            name="openrouter",
            source_url=f"{self._base_url}/api/v1/models",
            retrieved_at=clock,
            authoritative=True,
            stale=False,
        )

        return CatalogSnapshot(
            models=models,
            sources=(source,),
            retrieved_at=clock,
            stale=False,
            parse_warnings=tuple(parse_warnings),
        )

    def _parse_model(self, entry: dict[str, Any], *, clock: datetime) -> ModelProfile:
        model_id = str(entry["id"]).strip()
        if not model_id:
            raise ValueError("missing model id")

        canonical_id = canonical_model_id("openrouter", model_id)
        identity = ModelIdentity(
            provider="openrouter",
            model_id=model_id,
            canonical_id=canonical_id,
            display_name=_read_str(entry, "name"),
        )

        endpoint = ModelEndpoint(
            provider="openrouter",
            endpoint_id=model_id,
            api_base_url=self._base_url,
            supports_streaming=_bool_to_support(entry.get("supports_streaming")),
            metadata={"top_provider": entry.get("top_provider")},
        )

        capabilities = _build_capabilities(entry)
        pricing = _build_pricing(entry.get("pricing"), entry.get("pricing_overrides"))

        source = CatalogSource(
            name="openrouter",
            source_url=f"{self._base_url}/api/v1/models",
            retrieved_at=clock,
            authoritative=True,
            stale=False,
            metadata={"response_id": model_id},
        )

        return ModelProfile(
            identity=identity,
            endpoints=(endpoint,),
            capabilities=capabilities,
            pricing=pricing,
            sources=(source,),
            retrieved_at=clock,
            raw_refs={"openrouter_model_id": model_id},
            provenance={"identity": {"openrouter": model_id}},
        )

    def _cache_file(self) -> Path:
        return self._cache_dir / "openrouter_catalog.json"

    def _load_cache(self, *, offline: bool) -> CatalogSnapshot | None:
        cache_path = self._cache_file()
        if not cache_path.exists():
            return None

        try:
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise TypeError("cache must be a JSON object")
            snapshot_data = payload["snapshot"]
            snapshot = CatalogSnapshot.model_validate(snapshot_data)
        except Exception as exc:
            if offline:
                raise CatalogCacheError(
                    "catalog cache is corrupt and offline mode forbids refresh"
                ) from exc
            return None
        else:
            return snapshot

    def _write_cache(self, *, snapshot: CatalogSnapshot, raw_payload: dict[str, Any]) -> None:
        self._cache_dir.mkdir(parents=True, exist_ok=True)
        destination = self._cache_file()
        payload = {
            "cache_format_version": _CACHE_VERSION,
            "fetched_at": snapshot.retrieved_at.isoformat(),
            "source_url": f"{self._base_url}/api/v1/models",
            "ttl_seconds": int(self._ttl.total_seconds()),
            "raw_payload": raw_payload,
            "snapshot": snapshot.model_dump(mode="json"),
        }

        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=self._cache_dir,
            prefix="openrouter_catalog_",
            suffix=".tmp",
            delete=False,
        ) as tmp_file:
            json.dump(payload, tmp_file, indent=2, sort_keys=True)
            tmp_path = Path(tmp_file.name)

        tmp_path.replace(destination)


def _build_capabilities(entry: dict[str, Any]) -> ModelCapabilities:
    raw_architecture = entry.get("architecture")
    architecture: dict[str, Any] = raw_architecture if isinstance(raw_architecture, dict) else {}

    input_modalities = tuple(_as_str_list(architecture.get("input_modalities")))
    output_modalities = tuple(_as_str_list(architecture.get("output_modalities")))

    supported_params = tuple(_as_str_list(entry.get("supported_parameters")))

    return ModelCapabilities(
        context_length=_as_int(entry.get("context_length") or entry.get("context_window")),
        max_output_tokens=_as_int(entry.get("max_output_tokens")),
        input_modalities=input_modalities,
        output_modalities=output_modalities,
        tools=_bool_to_support(entry.get("supports_tools")),
        structured_output=_bool_to_support(entry.get("supports_structured_output")),
        json_mode=_bool_to_support(entry.get("supports_json_mode")),
        reasoning=_bool_to_support(entry.get("supports_reasoning")),
        streaming=_bool_to_support(entry.get("supports_streaming")),
        embeddings=_bool_to_support(entry.get("supports_embeddings")),
        image=_flag_from_modalities("image", input_modalities, output_modalities),
        audio=_flag_from_modalities("audio", input_modalities, output_modalities),
        video=_flag_from_modalities("video", input_modalities, output_modalities),
        supported_parameters=supported_params,
        extra_metadata={
            key: value
            for key, value in entry.items()
            if key
            not in {
                "id",
                "name",
                "context_length",
                "context_window",
                "max_output_tokens",
                "supported_parameters",
                "pricing",
                "pricing_overrides",
                "architecture",
                "supports_tools",
                "supports_structured_output",
                "supports_json_mode",
                "supports_reasoning",
                "supports_streaming",
                "supports_embeddings",
            }
        },
    )


def _build_pricing(pricing_payload: object, overrides_payload: object) -> Pricing:
    components: dict[str, PriceComponent] = {}
    unknown_components: dict[str, PriceComponent] = {}
    source_by_key: dict[str, str] = {}

    if isinstance(pricing_payload, dict):
        for key, raw_value in pricing_payload.items():
            if raw_value is None:
                continue
            component = PriceComponent(key=key, amount=raw_value)
            if key in KNOWN_OPENROUTER_PRICE_KEYS:
                components[key] = component
            else:
                unknown_components[key] = component
            source_by_key[key] = "openrouter"

    overrides: list[PricingOverride] = []
    if isinstance(overrides_payload, list):
        for idx, raw_override in enumerate(overrides_payload):
            if not isinstance(raw_override, dict):
                continue
            raw_prices = raw_override.get("prices")
            if not isinstance(raw_prices, dict):
                continue
            normalized_prices = {
                key: PriceComponent(key=key, amount=value)
                for key, value in raw_prices.items()
                if value is not None
            }
            overrides.append(
                PricingOverride(
                    name=str(raw_override.get("name") or f"override-{idx}"),
                    prompt_tokens_gte=_as_int(raw_override.get("prompt_tokens_gte")),
                    utc_window_start=_as_time(raw_override.get("utc_window_start")),
                    utc_window_end=_as_time(raw_override.get("utc_window_end")),
                    prices=normalized_prices,
                    metadata={
                        key: value
                        for key, value in raw_override.items()
                        if key
                        not in {
                            "name",
                            "prompt_tokens_gte",
                            "utc_window_start",
                            "utc_window_end",
                            "prices",
                        }
                    },
                )
            )

    return Pricing(
        components=components,
        overrides=tuple(overrides),
        unknown_components=unknown_components,
        provenance=PricingProvenance(source_by_key=source_by_key),
    )


def _mark_stale_if_needed(
    snapshot: CatalogSnapshot, *, now: datetime, ttl: timedelta
) -> CatalogSnapshot:
    stale = _is_expired(snapshot.retrieved_at, now=now, ttl=ttl)
    if not stale:
        return snapshot
    return snapshot.model_copy(update={"stale": True})


def _is_expired(retrieved_at: datetime, *, now: datetime, ttl: timedelta) -> bool:
    return now - retrieved_at > ttl


def _bool_to_support(value: object) -> SupportStatus:
    if value is True:
        return SupportStatus.SUPPORTED
    if value is False:
        return SupportStatus.UNSUPPORTED
    return SupportStatus.UNKNOWN


def _as_str_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if isinstance(item, (str, int))]


def _as_int(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip():
        try:
            return int(value)
        except ValueError:
            return None
    return None


def _as_time(value: object) -> time | None:
    if value is None:
        return None
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return time.fromisoformat(value)
        except ValueError:
            return None
    return None


def _read_str(payload: dict[str, Any], key: str) -> str | None:
    value = payload.get(key)
    if isinstance(value, str) and value.strip():
        return value
    return None


def _flag_from_modalities(
    name: str,
    input_modalities: tuple[str, ...],
    output_modalities: tuple[str, ...],
) -> SupportStatus:
    if name in input_modalities or name in output_modalities:
        return SupportStatus.SUPPORTED
    return SupportStatus.UNKNOWN
