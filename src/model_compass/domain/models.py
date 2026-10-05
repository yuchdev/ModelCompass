"""Provider-independent domain models for model catalogs."""

from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal, InvalidOperation
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

KNOWN_OPENROUTER_PRICE_KEYS: tuple[str, ...] = (
    "prompt",
    "completion",
    "request",
    "image",
    "audio",
    "web_search",
    "internal_reasoning",
    "input_cache_read",
    "input_cache_write",
)


class SupportStatus(StrEnum):
    """Tri-state support capability status."""

    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ModelIdentity(BaseModel):
    """Canonical model identity."""

    model_config = ConfigDict(frozen=True)

    provider: str
    model_id: str
    canonical_id: str
    display_name: str | None = None

    @field_validator("provider", "model_id", "canonical_id")
    @classmethod
    def _not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("identity fields must be non-empty")
        return value


class ModelEndpoint(BaseModel):
    """Endpoint representation for a model."""

    model_config = ConfigDict(frozen=True)

    provider: str
    endpoint_id: str
    api_base_url: str | None = None
    supports_streaming: SupportStatus = SupportStatus.UNKNOWN
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelCapabilities(BaseModel):
    """Normalized capability flags and metadata."""

    model_config = ConfigDict(frozen=True)

    context_length: int | None = None
    max_output_tokens: int | None = None
    input_modalities: tuple[str, ...] = ()
    output_modalities: tuple[str, ...] = ()
    tools: SupportStatus = SupportStatus.UNKNOWN
    structured_output: SupportStatus = SupportStatus.UNKNOWN
    json_mode: SupportStatus = SupportStatus.UNKNOWN
    reasoning: SupportStatus = SupportStatus.UNKNOWN
    streaming: SupportStatus = SupportStatus.UNKNOWN
    embeddings: SupportStatus = SupportStatus.UNKNOWN
    image: SupportStatus = SupportStatus.UNKNOWN
    audio: SupportStatus = SupportStatus.UNKNOWN
    video: SupportStatus = SupportStatus.UNKNOWN
    supported_parameters: tuple[str, ...] = ()
    extra_metadata: dict[str, Any] = Field(default_factory=dict)


class PriceComponent(BaseModel):
    """Single normalized price component."""

    model_config = ConfigDict(frozen=True)

    key: str
    amount: Decimal
    currency: str = "USD"
    unit: str = "unit"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("amount", mode="before")
    @classmethod
    def _parse_amount(cls, value: object) -> Decimal:
        return parse_decimal(value)

    @field_validator("amount")
    @classmethod
    def _non_negative(cls, value: Decimal) -> Decimal:
        if value < Decimal("0"):
            raise ValueError("price must be non-negative")
        return value


class PricingOverride(BaseModel):
    """Conditional override for one or more price keys."""

    model_config = ConfigDict(frozen=True)

    name: str
    prompt_tokens_gte: int | None = None
    utc_window_start: time | None = None
    utc_window_end: time | None = None
    prices: dict[str, PriceComponent]
    metadata: dict[str, Any] = Field(default_factory=dict)

    def applies(self, *, prompt_tokens: int, now_utc: datetime) -> bool:
        """Return True when this override is applicable."""
        if self.prompt_tokens_gte is not None and prompt_tokens < self.prompt_tokens_gte:
            return False

        if self.utc_window_start is None or self.utc_window_end is None:
            return True

        current = now_utc.time()
        if self.utc_window_start <= self.utc_window_end:
            return self.utc_window_start <= current < self.utc_window_end

        return current >= self.utc_window_start or current < self.utc_window_end


class PricingProvenance(BaseModel):
    """Per-key pricing source and disagreements."""

    model_config = ConfigDict(frozen=True)

    source_by_key: dict[str, str] = Field(default_factory=dict)
    disagreements: dict[str, dict[str, str]] = Field(default_factory=dict)


class Pricing(BaseModel):
    """Base prices plus conditional overrides."""

    model_config = ConfigDict(frozen=True)

    components: dict[str, PriceComponent] = Field(default_factory=dict)
    overrides: tuple[PricingOverride, ...] = ()
    unknown_components: dict[str, PriceComponent] = Field(default_factory=dict)
    provenance: PricingProvenance = Field(default_factory=PricingProvenance)

    def effective_components(
        self,
        *,
        prompt_tokens: int = 0,
        now_utc: datetime | None = None,
    ) -> dict[str, PriceComponent]:
        """Return effective pricing after applying applicable overrides."""
        resolved = dict(self.components)
        now = now_utc or datetime.now(UTC)

        for override in self.overrides:
            if override.applies(prompt_tokens=prompt_tokens, now_utc=now):
                resolved.update(override.prices)

        return resolved


class CatalogSource(BaseModel):
    """Source metadata for an ingested catalog."""

    model_config = ConfigDict(frozen=True)

    name: str
    source_url: str | None = None
    retrieved_at: datetime
    authoritative: bool = False
    stale: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class ModelProfile(BaseModel):
    """Normalized model aggregate used by application and selection layers."""

    model_config = ConfigDict(frozen=True)

    identity: ModelIdentity
    endpoints: tuple[ModelEndpoint, ...] = ()
    capabilities: ModelCapabilities = Field(default_factory=ModelCapabilities)
    pricing: Pricing = Field(default_factory=Pricing)
    sources: tuple[CatalogSource, ...] = ()
    retrieved_at: datetime
    raw_refs: dict[str, str] = Field(default_factory=dict)
    provenance: dict[str, dict[str, str]] = Field(default_factory=dict)


class CatalogSnapshot(BaseModel):
    """Single-source or merged catalog snapshot."""

    model_config = ConfigDict(frozen=True)

    models: dict[str, ModelProfile]
    sources: tuple[CatalogSource, ...]
    retrieved_at: datetime
    stale: bool = False
    parse_warnings: tuple[str, ...] = ()


class CatalogMergeResult(BaseModel):
    """Result of deterministic catalog merging."""

    model_config = ConfigDict(frozen=True)

    snapshot: CatalogSnapshot
    conflicts: dict[str, Any] = Field(default_factory=dict)


def canonical_model_id(provider: str, model_id: str) -> str:
    """Build a stable canonical ID from provider and model id."""
    return f"{provider.strip().lower()}:{model_id.strip().lower()}"


def parse_decimal(value: object) -> Decimal:
    """Parse money values into Decimal using string-safe conversion."""
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    if isinstance(value, str):
        try:
            return Decimal(value)
        except InvalidOperation as exc:  # pragma: no cover - exercised via tests
            raise ValueError(f"invalid decimal string: {value}") from exc
    if isinstance(value, float):
        return Decimal(str(value))

    raise ValueError(f"unsupported decimal input type: {type(value)!r}")
