"""Deterministic catalog merge rules."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from model_compass.domain import (
    CatalogMergeResult,
    CatalogSnapshot,
    ModelCapabilities,
    ModelProfile,
    PriceComponent,
    Pricing,
    PricingProvenance,
    SupportStatus,
)


def merge_catalog_snapshots(
    primary: CatalogSnapshot,
    secondary: CatalogSnapshot,
    *,
    now_utc: datetime | None = None,
) -> CatalogMergeResult:
    """Merge two snapshots where primary wins on conflicts unless unknown."""
    clock = now_utc or datetime.now(UTC)
    merged_models: dict[str, ModelProfile] = {}
    conflicts: dict[str, Any] = {}

    model_ids = sorted(set(primary.models.keys()) | set(secondary.models.keys()))
    for model_id in model_ids:
        primary_profile = primary.models.get(model_id)
        secondary_profile = secondary.models.get(model_id)

        if primary_profile is None and secondary_profile is not None:
            merged_models[model_id] = secondary_profile
            continue

        if secondary_profile is None and primary_profile is not None:
            merged_models[model_id] = primary_profile
            continue

        if primary_profile is None or secondary_profile is None:
            raise ValueError("invariant violation while merging model profiles")
        merged, model_conflicts = _merge_profiles(primary_profile, secondary_profile)
        if model_conflicts:
            conflicts[model_id] = model_conflicts
        merged_models[model_id] = merged

    snapshot = CatalogSnapshot(
        models=merged_models,
        sources=(*primary.sources, *secondary.sources),
        retrieved_at=clock,
        stale=primary.stale or secondary.stale,
        parse_warnings=(*primary.parse_warnings, *secondary.parse_warnings),
    )
    return CatalogMergeResult(snapshot=snapshot, conflicts=conflicts)


def _merge_profiles(
    primary: ModelProfile,
    secondary: ModelProfile,
) -> tuple[ModelProfile, dict[str, Any]]:
    if primary.identity.canonical_id != secondary.identity.canonical_id:
        raise ValueError("cannot merge mismatched model identities")

    capability, capability_conflicts = _merge_capabilities(
        primary.capabilities, secondary.capabilities
    )
    pricing, pricing_conflicts = _merge_pricing(primary, secondary)

    sources = _dedupe_sources((*primary.sources, *secondary.sources))
    provenance = dict(primary.provenance)
    for key, value in secondary.provenance.items():
        target = provenance.setdefault(key, {})
        target.update(value)

    for field, values in capability_conflicts.items():
        provenance.setdefault(field, {}).update(values)
    for field, values in pricing_conflicts.items():
        provenance.setdefault(f"pricing.{field}", {}).update(values)

    conflicts: dict[str, Any] = {}
    if capability_conflicts:
        conflicts["capabilities"] = capability_conflicts
    if pricing_conflicts:
        conflicts["pricing"] = pricing_conflicts

    merged_profile = ModelProfile(
        identity=primary.identity,
        endpoints=primary.endpoints or secondary.endpoints,
        capabilities=capability,
        pricing=pricing,
        sources=sources,
        retrieved_at=max(primary.retrieved_at, secondary.retrieved_at),
        raw_refs={**secondary.raw_refs, **primary.raw_refs},
        provenance=provenance,
    )
    return merged_profile, conflicts


def _merge_capabilities(
    primary: ModelCapabilities,
    secondary: ModelCapabilities,
) -> tuple[ModelCapabilities, dict[str, dict[str, str]]]:
    payload = primary.model_dump()
    conflicts: dict[str, dict[str, str]] = {}

    for field_name in (
        "tools",
        "structured_output",
        "json_mode",
        "reasoning",
        "streaming",
        "embeddings",
        "image",
        "audio",
        "video",
    ):
        p_value = getattr(primary, field_name)
        s_value = getattr(secondary, field_name)

        if p_value == SupportStatus.UNKNOWN and s_value != SupportStatus.UNKNOWN:
            payload[field_name] = s_value
        elif (
            p_value != SupportStatus.UNKNOWN
            and s_value != SupportStatus.UNKNOWN
            and p_value != s_value
        ):
            conflicts[field_name] = {"primary": p_value.value, "secondary": s_value.value}

    for field_name in ("context_length", "max_output_tokens"):
        p_value = getattr(primary, field_name)
        s_value = getattr(secondary, field_name)
        if p_value is None and s_value is not None:
            payload[field_name] = s_value
        elif p_value is not None and s_value is not None and p_value != s_value:
            conflicts[field_name] = {"primary": str(p_value), "secondary": str(s_value)}

    if not primary.input_modalities and secondary.input_modalities:
        payload["input_modalities"] = secondary.input_modalities
    if not primary.output_modalities and secondary.output_modalities:
        payload["output_modalities"] = secondary.output_modalities
    if not primary.supported_parameters and secondary.supported_parameters:
        payload["supported_parameters"] = secondary.supported_parameters

    extra = dict(secondary.extra_metadata)
    extra.update(primary.extra_metadata)
    payload["extra_metadata"] = extra

    return ModelCapabilities(**payload), conflicts


def _is_primary_authoritative(profile: ModelProfile) -> bool:
    return any(source.authoritative and not source.stale for source in profile.sources)


def _merge_pricing(
    primary_profile: ModelProfile,
    secondary_profile: ModelProfile,
) -> tuple[Pricing, dict[str, dict[str, str]]]:
    primary = primary_profile.pricing
    secondary = secondary_profile.pricing
    conflicts: dict[str, dict[str, str]] = {}

    components = dict(primary.components)
    source_by_key = dict(primary.provenance.source_by_key)
    disagreements = dict(primary.provenance.disagreements)

    primary_authoritative = _is_primary_authoritative(primary_profile)

    for key, sec_value in secondary.components.items():
        pri_value = components.get(key)
        if pri_value is None:
            components[key] = sec_value
            source_by_key.setdefault(
                key, secondary_profile.sources[0].name if secondary_profile.sources else "secondary"
            )
            continue

        if pri_value.amount != sec_value.amount:
            if not primary_authoritative:
                components[key] = sec_value
                source_by_key[key] = (
                    secondary_profile.sources[0].name if secondary_profile.sources else "secondary"
                )
            disagreements[key] = {
                "primary": str(pri_value.amount),
                "secondary": str(sec_value.amount),
            }
            conflicts[key] = disagreements[key]

    unknown = dict(secondary.unknown_components)
    unknown.update(primary.unknown_components)

    provenance = PricingProvenance(source_by_key=source_by_key, disagreements=disagreements)

    return Pricing(
        components=components,
        overrides=primary.overrides or secondary.overrides,
        unknown_components=unknown,
        provenance=provenance,
    ), conflicts


def _dedupe_sources(sources: tuple[Any, ...]) -> tuple[Any, ...]:
    seen: set[tuple[str, str]] = set()
    result = []
    for source in sources:
        key = (source.name, source.retrieved_at.isoformat())
        if key in seen:
            continue
        seen.add(key)
        result.append(source)
    return tuple(result)


def choose_price_value(
    primary: PriceComponent, secondary: PriceComponent, prefer_primary: bool
) -> Decimal:
    """Small helper retained for explicit unit tests around deterministic choice."""
    return primary.amount if prefer_primary else secondary.amount
