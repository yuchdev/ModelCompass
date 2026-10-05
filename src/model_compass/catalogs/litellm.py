"""LiteLLM metadata adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from model_compass.domain import (
    CatalogSnapshot,
    CatalogSource,
    ModelCapabilities,
    ModelEndpoint,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    PricingProvenance,
    SupportStatus,
    canonical_model_id,
)
from model_compass.exceptions import DependencyError


class LiteLLMCatalogAdapter:
    """Read model metadata from LiteLLM without importing it in domain modules."""

    async def refresh(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        now_utc: datetime | None = None,
    ) -> CatalogSnapshot:
        del force, offline
        clock = now_utc or datetime.now(UTC)

        try:
            import litellm
        except ImportError as exc:
            raise DependencyError("LiteLLM is required for LiteLLM catalog adapter") from exc

        models: dict[str, ModelProfile] = {}
        model_cost: dict[str, Any] = getattr(litellm, "model_cost", {})

        for model_name, payload in model_cost.items():
            if not isinstance(model_name, str) or not model_name.strip():
                continue
            if not isinstance(payload, dict):
                continue

            provider, normalized_model_id = _normalize_provider_model(model_name)
            canonical_id = canonical_model_id(provider, normalized_model_id)

            prompt_cost = payload.get("input_cost_per_token")
            if prompt_cost is None:
                prompt_cost = payload.get("prompt_cost_per_token")
            completion_cost = payload.get("output_cost_per_token")
            if completion_cost is None:
                completion_cost = payload.get("completion_cost_per_token")

            components = {}
            source_by_key = {}
            if prompt_cost is not None:
                components["prompt"] = PriceComponent(key="prompt", amount=prompt_cost)
                source_by_key["prompt"] = "litellm"
            if completion_cost is not None:
                components["completion"] = PriceComponent(key="completion", amount=completion_cost)
                source_by_key["completion"] = "litellm"

            capabilities = ModelCapabilities(
                context_length=_as_int(payload.get("max_input_tokens")),
                max_output_tokens=_as_int(payload.get("max_output_tokens")),
                streaming=SupportStatus.UNKNOWN,
                extra_metadata={
                    key: value
                    for key, value in payload.items()
                    if key
                    not in {
                        "input_cost_per_token",
                        "prompt_cost_per_token",
                        "output_cost_per_token",
                        "completion_cost_per_token",
                        "max_input_tokens",
                        "max_output_tokens",
                    }
                },
            )

            source = CatalogSource(
                name="litellm",
                source_url="litellm:model_cost",
                retrieved_at=clock,
                authoritative=False,
                stale=False,
            )

            profile = ModelProfile(
                identity=ModelIdentity(
                    provider=provider,
                    model_id=normalized_model_id,
                    canonical_id=canonical_id,
                    display_name=payload.get("display_name")
                    if isinstance(payload.get("display_name"), str)
                    else None,
                ),
                endpoints=(
                    ModelEndpoint(
                        provider=provider,
                        endpoint_id=normalized_model_id,
                        supports_streaming=SupportStatus.UNKNOWN,
                    ),
                ),
                capabilities=capabilities,
                pricing=Pricing(
                    components=components,
                    provenance=PricingProvenance(source_by_key=source_by_key),
                ),
                sources=(source,),
                retrieved_at=clock,
                raw_refs={"litellm_model": model_name},
                provenance={"identity": {"litellm": model_name}},
            )

            models[canonical_id] = profile

        source = CatalogSource(
            name="litellm",
            source_url="litellm:model_cost",
            retrieved_at=clock,
            authoritative=False,
            stale=False,
        )

        return CatalogSnapshot(models=models, sources=(source,), retrieved_at=clock)


def _normalize_provider_model(model_name: str) -> tuple[str, str]:
    normalized = model_name.strip()
    if "/" not in normalized:
        return "litellm", normalized

    prefix, remainder = normalized.split("/", maxsplit=1)
    if prefix.lower() == "openrouter":
        return "openrouter", remainder
    return prefix.lower(), remainder


def _as_int(value: object) -> int | None:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None
