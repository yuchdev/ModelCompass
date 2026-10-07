from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from model_compass.domain import (
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
)


def demo_profiles() -> tuple[ModelProfile, ModelProfile]:
    cheap = ModelProfile(
        identity=ModelIdentity(provider="demo", model_id="small", canonical_id="demo:small"),
        capabilities=ModelCapabilities(
            context_length=8_000,
            max_output_tokens=1_000,
            input_modalities=("text",),
            output_modalities=("text",),
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal("0.000001")),
                "completion": PriceComponent(key="completion", amount=Decimal("0.000002")),
            }
        ),
        retrieved_at=datetime.now(UTC),
    )
    better = ModelProfile(
        identity=ModelIdentity(provider="demo", model_id="large", canonical_id="demo:large"),
        capabilities=ModelCapabilities(
            context_length=16_000,
            max_output_tokens=2_000,
            input_modalities=("text",),
            output_modalities=("text",),
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal("0.000003")),
                "completion": PriceComponent(key="completion", amount=Decimal("0.000006")),
            }
        ),
        retrieved_at=datetime.now(UTC),
    )
    return cheap, better


def demo_request() -> RequestProfile:
    return RequestProfile(
        task="summarization",
        explicit_input_tokens=2_000,
        expected_output_tokens=500,
        max_cost_usd=Decimal("0.02"),
        min_quality=Decimal("0.85"),
    )
