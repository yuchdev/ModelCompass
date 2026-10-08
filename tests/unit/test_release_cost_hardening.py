"""Release-candidate regression tests for custom metered cost components."""

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from model_compass.domain import ModelIdentity, ModelProfile, PriceComponent, Pricing
from model_compass.metrics import TokenEstimate, estimate_cost


def _profile() -> ModelProfile:
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id="metered", canonical_id="test:metered"),
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
def test_custom_component_is_charged_exactly_once() -> None:
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
def test_builtin_usage_cannot_be_billed_twice(component: str) -> None:
    with pytest.raises(ValueError, match="overlaps built-in"):
        estimate_cost(
            _profile(),
            TokenEstimate(input_tokens=1, output_tokens=1, source="test", exact=True),
            unit_usage={component: 1},
        )


@pytest.mark.unit
@pytest.mark.parametrize("usage", [Decimal("NaN"), Decimal("Infinity"), -1, True, 0.1])
def test_invalid_custom_usage_rejected(usage: object) -> None:
    with pytest.raises(ValueError, match="unit usage"):
        estimate_cost(
            _profile(),
            TokenEstimate(input_tokens=1, output_tokens=1, source="test", exact=True),
            unit_usage={"image": usage},  # type: ignore[arg-type]
        )


@pytest.mark.unit
def test_unknown_custom_price_is_not_silently_zero() -> None:
    estimate = estimate_cost(
        _profile(),
        TokenEstimate(input_tokens=1, output_tokens=1, source="test", exact=True),
        unit_usage={"audio": 1},
    )
    assert not estimate.complete
    assert "Missing price for used component 'audio'." in estimate.assumptions
