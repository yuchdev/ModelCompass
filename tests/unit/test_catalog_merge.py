from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional

import pytest

from model_compass.catalogs.merge import merge_catalog_snapshots
from model_compass.domain import (
    CatalogSnapshot,
    CatalogSource,
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    PricingProvenance,
    SupportStatus,
    canonical_model_id,
)


def _profile(
    *,
    provider: str,
    model_id: str,
    source_name: str,
    authoritative: bool,
    prompt_price: Optional[Decimal],
    tools: SupportStatus,
) -> ModelProfile:
    """Build a single-source ModelProfile for merge tests."""
    now = datetime(2026, 1, 1, tzinfo=UTC)
    canonical = canonical_model_id(provider, model_id)
    components = {}
    provenance = {}
    if prompt_price is not None:
        components["prompt"] = PriceComponent(key="prompt", amount=prompt_price)
        provenance["prompt"] = source_name

    return ModelProfile(
        identity=ModelIdentity(provider=provider, model_id=model_id, canonical_id=canonical),
        capabilities=ModelCapabilities(tools=tools),
        pricing=Pricing(
            components=components,
            provenance=PricingProvenance(source_by_key=provenance),
        ),
        sources=(
            CatalogSource(
                name=source_name,
                retrieved_at=now,
                authoritative=authoritative,
            ),
        ),
        retrieved_at=now,
    )


@pytest.mark.unit
def test_merge_fills_unknown_capabilities_from_secondary():
    """[Unit] fill unknowns: an UNKNOWN primary capability is filled from the secondary source.

    Scenario: Merges a primary with UNKNOWN tools against a secondary that reports SUPPORTED.
    Boundaries: Pure merge logic over in-memory snapshots; no I/O.
    On failure, first check: the UNKNOWN-fill rule letting the secondary provide the value.
    """
    primary = _profile(
        provider="openrouter",
        model_id="x",
        source_name="openrouter",
        authoritative=True,
        prompt_price=Decimal("1"),
        tools=SupportStatus.UNKNOWN,
    )
    secondary = _profile(
        provider="openrouter",
        model_id="x",
        source_name="litellm",
        authoritative=False,
        prompt_price=None,
        tools=SupportStatus.SUPPORTED,
    )

    merged = merge_catalog_snapshots(
        CatalogSnapshot(
            models={primary.identity.canonical_id: primary},
            sources=primary.sources,
            retrieved_at=primary.retrieved_at,
        ),
        CatalogSnapshot(
            models={secondary.identity.canonical_id: secondary},
            sources=secondary.sources,
            retrieved_at=secondary.retrieved_at,
        ),
    ).snapshot

    profile = merged.models[primary.identity.canonical_id]
    assert profile.capabilities.tools == SupportStatus.SUPPORTED


@pytest.mark.unit
def test_merge_keeps_authoritative_pricing_and_records_conflict():
    """[Unit] authoritative wins: conflicting prices keep the authoritative value and log a conflict.

    Scenario: Merges an authoritative primary and a non-authoritative secondary with differing prices.
    Boundaries: Pure merge logic over in-memory snapshots; no I/O.
    On failure, first check: authoritative precedence and the recorded pricing conflict entry.
    """
    primary = _profile(
        provider="openrouter",
        model_id="x",
        source_name="openrouter",
        authoritative=True,
        prompt_price=Decimal("1"),
        tools=SupportStatus.UNKNOWN,
    )
    secondary = _profile(
        provider="openrouter",
        model_id="x",
        source_name="litellm",
        authoritative=False,
        prompt_price=Decimal("2"),
        tools=SupportStatus.UNKNOWN,
    )

    result = merge_catalog_snapshots(
        CatalogSnapshot(
            models={primary.identity.canonical_id: primary},
            sources=primary.sources,
            retrieved_at=primary.retrieved_at,
        ),
        CatalogSnapshot(
            models={secondary.identity.canonical_id: secondary},
            sources=secondary.sources,
            retrieved_at=secondary.retrieved_at,
        ),
    )

    profile = result.snapshot.models[primary.identity.canonical_id]
    assert profile.pricing.components["prompt"].amount == Decimal("1")
    assert result.conflicts[primary.identity.canonical_id]["pricing"]["prompt"]


@pytest.mark.unit
def test_merge_rejects_mismatched_identities():
    """[Unit] distinct ids preserved: profiles with different canonical ids both survive the merge.

    Scenario: Merges two snapshots whose models have different canonical ids.
    Boundaries: Pure merge logic over in-memory snapshots; no I/O.
    On failure, first check: that distinct identities are kept side by side rather than collapsed.
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    a = _profile(
        provider="openrouter",
        model_id="x",
        source_name="openrouter",
        authoritative=True,
        prompt_price=Decimal("1"),
        tools=SupportStatus.UNKNOWN,
    )
    b = _profile(
        provider="openrouter",
        model_id="y",
        source_name="litellm",
        authoritative=False,
        prompt_price=Decimal("2"),
        tools=SupportStatus.UNKNOWN,
    )
    first = CatalogSnapshot(models={a.identity.canonical_id: a}, sources=a.sources, retrieved_at=now)
    second = CatalogSnapshot(models={b.identity.canonical_id: b}, sources=b.sources, retrieved_at=now)

    merged = merge_catalog_snapshots(first, second).snapshot
    assert set(merged.models) == {a.identity.canonical_id, b.identity.canonical_id}


@pytest.mark.unit
def test_merge_secondary_pricing_wins_when_primary_not_authoritative():
    """[Unit] non-authoritative primary: the secondary price wins when neither source is authoritative.

    Scenario: Merges two non-authoritative sources with differing prompt prices.
    Boundaries: Pure merge logic over in-memory snapshots; no I/O.
    On failure, first check: the tie-break selecting the secondary price when primary is not authoritative.
    """
    primary = _profile(
        provider="litellm",
        model_id="x",
        source_name="litellm",
        authoritative=False,
        prompt_price=Decimal("1"),
        tools=SupportStatus.UNKNOWN,
    )
    secondary = _profile(
        provider="litellm",
        model_id="x",
        source_name="other",
        authoritative=False,
        prompt_price=Decimal("2"),
        tools=SupportStatus.UNKNOWN,
    )
    result = merge_catalog_snapshots(
        CatalogSnapshot(
            models={primary.identity.canonical_id: primary},
            sources=primary.sources,
            retrieved_at=primary.retrieved_at,
        ),
        CatalogSnapshot(
            models={secondary.identity.canonical_id: secondary},
            sources=secondary.sources,
            retrieved_at=secondary.retrieved_at,
        ),
    )
    assert result.snapshot.models[primary.identity.canonical_id].pricing.components["prompt"].amount == Decimal("2")
