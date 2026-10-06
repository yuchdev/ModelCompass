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
    RequestProfile,
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
def test_parse_decimal(raw: object, expected: Decimal):
    """[Unit] Parse decimal: verifies the described behaviour holds.

    Scenario: Exercises parse decimal and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    assert parse_decimal(raw) == expected


@pytest.mark.unit
@pytest.mark.parametrize("raw", [True, "not-a-price", object()])
def test_parse_decimal_raises_public_pricing_error(raw: object):
    """[Unit] Parse decimal raises public pricing error: verifies the described behaviour holds.

    Scenario: Exercises parse decimal raises public pricing error and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    with pytest.raises(PricingError):
        parse_decimal(raw)


@pytest.mark.unit
def test_support_status_unknown_by_default():
    """[Unit] Support status unknown by default: verifies the described behaviour holds.

    Scenario: Exercises support status unknown by default and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    assert SupportStatus.UNKNOWN.value == "unknown"


@pytest.mark.unit
def test_request_normalizes_modalities_and_rejects_empty_values():
    """[Unit] Request normalizes modalities and rejects empty values: verifies the described behaviour holds.

    Scenario: Exercises request normalizes modalities and rejects empty values and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    request = RequestProfile(input_modalities=frozenset({" Text ", "IMAGE"}))
    assert request.input_modalities == frozenset({"text", "image"})
    with pytest.raises(ValueError, match="modalities must contain non-empty"):
        RequestProfile(input_modalities=frozenset({""}))


@pytest.mark.unit
@pytest.mark.parametrize("value", [Decimal("NaN"), Decimal("Infinity")])
def test_price_rejects_non_finite_decimal(value: Decimal):
    """[Unit] Price rejects non finite decimal: verifies the described behaviour holds.

    Scenario: Exercises price rejects non finite decimal and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    with pytest.raises(ValueError, match="finite number"):
        PriceComponent(key="prompt", amount=value)


@pytest.mark.unit
def test_pricing_override_threshold_boundary():
    """[Unit] Pricing override threshold boundary: verifies the described behaviour holds.

    Scenario: Exercises pricing override threshold boundary and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
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
def test_utc_window_crossing_midnight():
    """[Unit] Utc window crossing midnight: verifies the described behaviour holds.

    Scenario: Exercises utc window crossing midnight and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
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
def test_later_overrides_win_per_key():
    """[Unit] Later overrides win per key: verifies the described behaviour holds.

    Scenario: Exercises later overrides win per key and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
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
def test_decimal_round_trip_hypothesis(value: Decimal):
    """[Unit] Decimal round trip hypothesis: verifies the described behaviour holds.

    Scenario: Exercises decimal round trip hypothesis and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    component = PriceComponent(key="prompt", amount=value)
    dumped = component.model_dump(mode="json")
    reloaded = PriceComponent.model_validate(dumped)
    assert reloaded.amount == component.amount


@pytest.mark.unit
def test_price_rejects_negative_decimal():
    """[Unit] Price rejects negative decimal: verifies the described behaviour holds.

    Scenario: Exercises price rejects negative decimal and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    with pytest.raises(ValueError, match="non-negative"):
        PriceComponent(key="prompt", amount=Decimal("-1"))
