from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest

from model_compass.catalogs.exceptions import CatalogParseError
from model_compass.catalogs.openrouter import OpenRouterCatalogAdapter
from model_compass.domain import canonical_model_id


def _fixture(name: str) -> dict[str, Any]:
    """Load and parse a catalog JSON fixture by file name."""
    root = Path(__file__).resolve().parents[1] / "fixtures" / "catalogs"
    return cast(dict[str, Any], json.loads((root / name).read_text(encoding="utf-8")))


@pytest.mark.unit
def test_unknown_pricing_field_preserved():
    """[Unit] unknown pricing kept: an unrecognized pricing key is preserved as an unknown component.

    Scenario: Parses a fixture carrying a 'quantum_compute' pricing key and inspects the profile.
    Boundaries: Pure parsing of a local fixture; no network.
    On failure, first check: unknown-pricing-key preservation into unknown_components.
    """
    adapter = OpenRouterCatalogAdapter()
    payload = _fixture("openrouter_unknown_pricing_field.json")
    snapshot = adapter._parse_payload(payload, clock=datetime(2026, 1, 1, tzinfo=UTC))

    profile = next(iter(snapshot.models.values()))
    assert "quantum_compute" in profile.pricing.unknown_components


@pytest.mark.unit
def test_conditional_pricing_override_parsed():
    """[Unit] conditional overrides: conditional pricing overrides are parsed into the pricing model.

    Scenario: Parses a fixture with two conditional pricing overrides and counts them.
    Boundaries: Pure parsing of a local fixture; no network.
    On failure, first check: conditional-override parsing populating pricing.overrides.
    """
    adapter = OpenRouterCatalogAdapter()
    payload = _fixture("openrouter_conditional_override.json")
    snapshot = adapter._parse_payload(payload, clock=datetime(2026, 1, 1, tzinfo=UTC))

    profile = next(iter(snapshot.models.values()))
    assert len(profile.pricing.overrides) == 2


@pytest.mark.unit
def test_top_level_malformed_fixture_rejected():
    """[Unit] malformed top level: a structurally invalid payload raises CatalogParseError.

    Scenario: Parses a fixture whose top-level shape is invalid and expects a parse error.
    Boundaries: Pure parsing of a local fixture; no network.
    On failure, first check: top-level schema validation raising CatalogParseError.
    """
    adapter = OpenRouterCatalogAdapter()
    payload = _fixture("openrouter_top_level_malformed.json")
    with pytest.raises(CatalogParseError):
        adapter._parse_payload(payload, clock=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.unit
def test_identity_normalization_canonical_strategy():
    """[Unit] canonical id: provider and model id are lowercased and trimmed into a canonical id.

    Scenario: Calls canonical_model_id with mixed-case, whitespace-padded inputs.
    Boundaries: Pure function; no I/O.
    On failure, first check: the normalization rules for casing and surrounding whitespace.
    """
    assert canonical_model_id("OpenRouter", " OpenAI/GPT-4o ") == "openrouter:openai/gpt-4o"
