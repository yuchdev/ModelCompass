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
    root = Path(__file__).resolve().parents[1] / "fixtures" / "catalogs"
    return cast(dict[str, Any], json.loads((root / name).read_text(encoding="utf-8")))


@pytest.mark.unit
def test_unknown_pricing_field_preserved() -> None:
    adapter = OpenRouterCatalogAdapter()
    payload = _fixture("openrouter_unknown_pricing_field.json")
    snapshot = adapter._parse_payload(payload, clock=datetime(2026, 1, 1, tzinfo=UTC))

    profile = next(iter(snapshot.models.values()))
    assert "quantum_compute" in profile.pricing.unknown_components


@pytest.mark.unit
def test_conditional_pricing_override_parsed() -> None:
    adapter = OpenRouterCatalogAdapter()
    payload = _fixture("openrouter_conditional_override.json")
    snapshot = adapter._parse_payload(payload, clock=datetime(2026, 1, 1, tzinfo=UTC))

    profile = next(iter(snapshot.models.values()))
    assert len(profile.pricing.overrides) == 2


@pytest.mark.unit
def test_top_level_malformed_fixture_rejected() -> None:
    adapter = OpenRouterCatalogAdapter()
    payload = _fixture("openrouter_top_level_malformed.json")
    with pytest.raises(CatalogParseError):
        adapter._parse_payload(payload, clock=datetime(2026, 1, 1, tzinfo=UTC))


@pytest.mark.unit
def test_identity_normalization_canonical_strategy() -> None:
    assert canonical_model_id("OpenRouter", " OpenAI/GPT-4o ") == "openrouter:openai/gpt-4o"
