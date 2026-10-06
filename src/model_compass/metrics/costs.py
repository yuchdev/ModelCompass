"""Request-specific cost estimation using normalized catalog prices."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from decimal import Decimal
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import ModelProfile, PriceComponent

from .tokens import TokenEstimate


class CostComponentEstimate(BaseModel):
    """Cost arithmetic for one priced usage component."""

    model_config = ConfigDict(frozen=True)

    component: str
    usage: Decimal = Field(ge=0)
    unit_price_usd: Decimal = Field(ge=0)
    cost_usd: Decimal = Field(ge=0)


class CostEstimate(BaseModel):
    """Total request cost, component breakdown, and completeness information."""

    model_config = ConfigDict(frozen=True)

    total: Decimal = Field(ge=0)
    components: tuple[CostComponentEstimate, ...] = ()
    pricing_source: Optional[str] = None
    token_estimate: TokenEstimate
    assumptions: tuple[str, ...] = ()
    complete: bool


def estimate_cost(
    model: ModelProfile,
    token_estimate: TokenEstimate,
    *,
    cached_input_read_tokens: int = 0,
    cached_input_write_tokens: int = 0,
    reasoning_tokens: Optional[int] = None,
    unit_usage: Optional[Mapping[str, Union[Decimal, int]]] = None,
    now_utc: Optional[datetime] = None,
) -> CostEstimate:
    """Estimate cost; missing prices for used components make it incomplete."""
    usage_values = {
        "input_cache_read": Decimal(cached_input_read_tokens),
        "input_cache_write": Decimal(cached_input_write_tokens),
        "internal_reasoning": Decimal(reasoning_tokens or 0),
    }
    if min(cached_input_read_tokens, cached_input_write_tokens, reasoning_tokens or 0) < 0:
        raise ValueError("token usage must be non-negative")
    if cached_input_read_tokens + cached_input_write_tokens > token_estimate.input_tokens:
        raise ValueError("cached input usage cannot exceed total input tokens")
    if reasoning_tokens is not None and reasoning_tokens > token_estimate.output_tokens:
        raise ValueError("reasoning token usage cannot exceed total output tokens")

    cached_total = cached_input_read_tokens + cached_input_write_tokens
    regular_input = token_estimate.input_tokens - cached_total
    regular_output = token_estimate.output_tokens - (reasoning_tokens or 0)
    usage_values["prompt"] = Decimal(regular_input)
    usage_values["completion"] = Decimal(regular_output)
    for key, usage in (unit_usage or {}).items():
        parsed = Decimal(usage)
        if parsed < 0:
            raise ValueError("unit usage must be non-negative")
        usage_values[key] = usage_values.get(key, Decimal(0)) + parsed

    prices = model.pricing.effective_components(
        prompt_tokens=token_estimate.input_tokens,
        now_utc=now_utc or datetime.now(UTC),
    )
    components: list[CostComponentEstimate] = []
    assumptions: list[str] = []
    complete = True
    total = Decimal(0)

    for key in (
        "prompt",
        "completion",
        "input_cache_read",
        "input_cache_write",
        "internal_reasoning",
    ):
        priced = _add_priced_usage(
            key,
            usage_values.get(key, Decimal(0)),
            prices.get(key),
            components,
            assumptions,
        )
        if not priced and usage_values.get(key, Decimal(0)) > 0 and prices.get(key) is not None:
            complete = False
        if usage_values.get(key, Decimal(0)) > 0 and prices.get(key) is None:
            complete = False

    for key, usage in sorted((unit_usage or {}).items()):
        price = prices.get(key)
        priced = _add_priced_usage(key, Decimal(usage), price, components, assumptions)
        if not priced and usage > 0 and price is not None:
            complete = False
        if usage > 0 and price is None:
            complete = False

    request_price = prices.get("request")
    if request_price is not None:
        if not _add_priced_usage("request", Decimal(1), request_price, components, assumptions):
            complete = False
    elif "request" in model.pricing.unknown_components:
        complete = False
        assumptions.append("A request fee is listed but its price is unknown.")

    for component in components:
        total += component.cost_usd
    sources = {model.pricing.provenance.source_by_key.get(component.component, "catalog") for component in components}
    pricing_source = ", ".join(sorted(sources)) if sources else None

    for key, usage in usage_values.items():
        if usage > 0 and prices.get(key) is None:
            assumptions.append(f"Missing price for used component '{key}'.")
    for key, usage in sorted((unit_usage or {}).items()):
        if usage > 0 and prices.get(key) is None:
            assumptions.append(f"Missing price for used component '{key}'.")
    if token_estimate.notes:
        assumptions.extend(token_estimate.notes)

    return CostEstimate(
        total=total,
        components=tuple(components),
        pricing_source=pricing_source,
        token_estimate=token_estimate,
        assumptions=tuple(dict.fromkeys(assumptions)),
        complete=complete,
    )


def _add_priced_usage(
    key: str,
    usage: Decimal,
    price: Optional[PriceComponent],
    components: list[CostComponentEstimate],
    assumptions: list[str],
) -> bool:
    """Append a priced usage component and return whether one was added."""
    if usage <= 0 or price is None:
        return True
    if price.currency.upper() != "USD":
        assumptions.append(f"Cannot convert {key} price from {price.currency} to USD.")
        return False
    components.append(
        CostComponentEstimate(
            component=key,
            usage=usage,
            unit_price_usd=price.amount,
            cost_usd=usage * price.amount,
        )
    )
    return True
