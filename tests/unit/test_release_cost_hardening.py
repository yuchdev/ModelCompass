"""Release-candidate regression tests for custom metered cost components."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from model_compass.domain import ModelCapabilities, ModelIdentity, ModelProfile, PriceComponent, Pricing
from model_compass.metrics import TokenEstimate, estimate_cost


def _profile() -> ModelProfile:
    """Create a sample model profile with metered price components for tests."""
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id="metered", canonical_id="test:metered"),
        capabilities=ModelCapabilities(),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal("0.01")),
                "completion": PriceComponent(key="completion", amount=Decimal("0.02")),
                "image": PriceComponent(key="image", amount=Decimal("0.03")),
            }
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.unit
def test_custom_component_is_charged_exactly_once():
    """[Unit] custom component charged once: custom metered unit usage is billed exactly once in cost estimates.

    Scenario: Estimates cost with custom unit usage for an image component and asserts total and component breakdown.
    Boundaries: In-memory cost calculation; no network or external dependencies.
    On failure, first check: estimate_cost component accumulation and unit usage multiplication logic.
    """
    estimate = estimate_cost(
        _profile(),
        TokenEstimate(input_tokens=2, output_tokens=3, source="test", exact=True),
        unit_usage={"image": Decimal("2")},
    )
    assert estimate.complete
    assert estimate.total == Decimal("0.14")
    assert [component.component for component in estimate.components] == [
        "prompt",
        "completion",
        "image",
    ]
    assert estimate.model_dump(mode="json")["total"] == "0.14"


@pytest.mark.unit
@pytest.mark.parametrize(
    "component",
    ["prompt", "completion", "request", "input_cache_read", "input_cache_write", "internal_reasoning"],
)
def test_builtin_usage_cannot_be_billed_twice(component: str):
    """[Unit] builtin usage collision: unit usage overlapping built-in billing keys raises ValueError.

    Scenario: Attempts to pass built-in components in unit_usage dictionary and asserts ValueError is raised.
    Boundaries: In-memory validation logic; no external dependencies.
    On failure, first check: estimate_cost validation preventing duplicate built-in component keys.
    """
    with pytest.raises(ValueError, match="overlaps built-in"):
        estimate_cost(
            _profile(),
            TokenEstimate(input_tokens=1, output_tokens=1, source="test", exact=True),
            unit_usage={component: 1},
        )


@pytest.mark.unit
@pytest.mark.parametrize("usage", [Decimal("NaN"), Decimal("Infinity"), -1, True, 0.1])
def test_invalid_custom_usage_rejected(usage: object):
    """[Unit] invalid custom usage: non-finite or negative usage values are rejected.

    Scenario: Passes invalid usage values like NaN, Infinity, negative, or boolean to unit_usage and asserts ValueError.
    Boundaries: In-memory validation logic; no external dependencies.
    On failure, first check: estimate_cost unit_usage value validation and decimal conversion checks.
    """
    with pytest.raises(ValueError, match="unit usage"):
        estimate_cost(
            _profile(),
            TokenEstimate(input_tokens=1, output_tokens=1, source="test", exact=True),
            unit_usage={"image": usage},  # type: ignore[dict-item]
        )


@pytest.mark.unit
def test_unknown_custom_price_is_not_silently_zero():
    """[Unit] missing custom price: missing pricing for custom unit usage marks estimate incomplete.

    Scenario: Estimates cost for an unpriced unit usage component and asserts incomplete status and assumption note.
    Boundaries: In-memory cost calculation; no external dependencies.
    On failure, first check: estimate_cost handling of missing price components in assumptions.
    """
    estimate = estimate_cost(
        _profile(),
        TokenEstimate(input_tokens=1, output_tokens=1, source="test", exact=True),
        unit_usage={"audio": 1},
    )
    assert not estimate.complete
    assert "Missing price for used component 'audio'." in estimate.assumptions
