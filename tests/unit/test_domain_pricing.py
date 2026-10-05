from __future__ import annotations

from datetime import UTC, datetime, time
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from model_compass.domain import (
    PriceComponent,
    Pricing,
    PricingOverride,
    SupportStatus,
    parse_decimal,
)
from model_compass.exceptions import PricingError


@pytest.mark.unit
@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0.1", Decimal("0.1")),
        (1, Decimal("1")),
        (1.25, Decimal("1.25")),
    ],
)
def test_parse_decimal(raw: object, expected: Decimal) -> None:
    assert parse_decimal(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", [True, "not-a-price", object()])
def test_parse_decimal_raises_public_pricing_error(raw: object) -> None:
    with pytest.raises(PricingError):
        parse_decimal(raw)


@pytest.mark.unit
def test_support_status_unknown_by_default() -> None:
    assert SupportStatus.UNKNOWN.value == "unknown"


@pytest.mark.unit
def test_request_normalizes_modalities_and_rejects_empty_values() -> None:
    from model_compass.domain import RequestProfile

    request = RequestProfile(input_modalities=frozenset({" Text ", "IMAGE"}))
    assert request.input_modalities == frozenset({"text", "image"})
    with pytest.raises(ValueError, match="modalities must not contain empty"):
        RequestProfile(input_modalities=frozenset({""}))


@pytest.mark.unit
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_price_rejects_non_finite_decimal(value: Decimal) -> None:
    with pytest.raises(ValueError, match="finite number"):
        PriceComponent(key="prompt", amount=value)


@pytest.mark.unit
def test_pricing_override_threshold_boundary() -> None:
    pricing = Pricing(
        components={"prompt": PriceComponent(key="prompt", amount=Decimal("2"))},
        overrides=(
            PricingOverride(
                name="tier",
                prompt_tokens_gte=100,
                prices={"prompt": PriceComponent(key="prompt", amount=Decimal("1"))},
            ),
        ),
    )

    assert pricing.effective_components(prompt_tokens=99)["prompt"].amount == Decimal("2")
    assert pricing.effective_components(prompt_tokens=100)["prompt"].amount == Decimal("1")


@pytest.mark.unit
def test_utc_window_crossing_midnight() -> None:
    override = PricingOverride(
        name="night",
        utc_window_start=time(22, 0),
        utc_window_end=time(2, 0),
        prices={"completion": PriceComponent(key="completion", amount=Decimal("1"))},
    )

    assert override.applies(prompt_tokens=0, now_utc=datetime(2026, 1, 1, 23, 0, tzinfo=UTC))
    assert override.applies(prompt_tokens=0, now_utc=datetime(2026, 1, 2, 1, 59, tzinfo=UTC))
    assert not override.applies(prompt_tokens=0, now_utc=datetime(2026, 1, 2, 2, 0, tzinfo=UTC))


@pytest.mark.unit
def test_later_overrides_win_per_key() -> None:
    pricing = Pricing(
        components={"prompt": PriceComponent(key="prompt", amount=Decimal("5"))},
        overrides=(
            PricingOverride(
                name="one",
                prices={"prompt": PriceComponent(key="prompt", amount=Decimal("4"))},
            ),
            PricingOverride(
                name="two",
                prices={"prompt": PriceComponent(key="prompt", amount=Decimal("3"))},
            ),
        ),
    )

    assert pricing.effective_components()["prompt"].amount == Decimal("3")


@given(st.decimals(min_value=0, max_value=1000, allow_nan=False, allow_infinity=False, places=6))
@pytest.mark.unit
def test_decimal_round_trip_hypothesis(value: Decimal) -> None:
    component = PriceComponent(key="prompt", amount=value)
    dumped = component.model_dump(mode="json")
    reloaded = PriceComponent.model_validate(dumped)
    assert reloaded.amount == component.amount
