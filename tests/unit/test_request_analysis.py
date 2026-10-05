from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st
from pydantic import ValidationError

from model_compass.domain import (
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    PricingOverride,
    RequestProfile,
    SupportStatus,
    build_request_profile,
)
from model_compass.metrics import FallbackTokenEstimator, TokenEstimate, estimate_cost
from model_compass.selection import (
    MissingDataPolicy,
    check_eligibility,
    compare_models,
    custom_workload_scenario,
    workload_scenario,
)


def _model(
    *,
    capabilities: ModelCapabilities | None = None,
    pricing: Pricing | None = None,
) -> ModelProfile:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id="model", canonical_id="test:model"),
        capabilities=capabilities or ModelCapabilities(),
        pricing=pricing or Pricing(),
        retrieved_at=now,
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("explicit_input_tokens", -1),
        ("expected_output_tokens", -1),
        ("minimum_context", -1),
        ("max_cost_usd", Decimal("-0.01")),
        ("min_quality", Decimal("1.01")),
        ("min_reliability", Decimal("-0.01")),
        ("max_latency_ms", -1),
    ],
)
def test_profile_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValidationError):
        RequestProfile.model_validate({field: value})


@pytest.mark.unit
def test_request_inference_and_explicit_precedence() -> None:
    profile = build_request_profile(
        prompt="Describe this",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Describe this"},
                    {"type": "image_url", "image_url": {"url": "local-image"}},
                ],
            }
        ],
        tools=[{"type": "function", "function": {"name": "lookup"}}],
        response_schema={"type": "object"},
        explicit_input_tokens=20,
        expected_output_tokens=5,
        requires_tools=False,
        input_modalities={"audio"},
    )
    assert profile.input_modalities == frozenset({"audio"})
    assert profile.requires_tools is False
    assert profile.requires_structured_output is True
    assert profile.minimum_context == 25
    assumptions = profile.metadata["inference_assumptions"]
    assert isinstance(assumptions, tuple)
    assert isinstance(assumptions[0], str)
    assert "explicit_input_tokens" in assumptions[0]


@pytest.mark.unit
def test_request_profile_infers_image_and_deterministic_minimum_context() -> None:
    profile = RequestProfile.from_request(
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "look"},
                    {"type": "image", "source": {"data": "x"}},
                ],
            }
        ],
        expected_output_tokens=12,
    )
    assert profile.input_modalities == frozenset({"text", "image"})
    assert profile.minimum_context is not None
    assert profile.minimum_context >= 12
    assumptions = profile.metadata["inference_assumptions"]
    assert isinstance(assumptions, tuple)
    assert isinstance(assumptions[0], str)
    assert "approximated" in assumptions[0]


@pytest.mark.unit
@pytest.mark.parametrize(
    ("capabilities", "profile", "eligible", "reason"),
    [
        (
            ModelCapabilities(context_length=99),
            RequestProfile(minimum_context=100),
            False,
            "context length",
        ),
        (
            ModelCapabilities(input_modalities=("text",)),
            RequestProfile(input_modalities=frozenset({"image"})),
            False,
            "unsupported input modality",
        ),
        (
            ModelCapabilities(tools=SupportStatus.UNSUPPORTED),
            RequestProfile(requires_tools=True),
            False,
            "tools is required",
        ),
        (
            ModelCapabilities(structured_output=SupportStatus.UNSUPPORTED),
            RequestProfile(requires_structured_output=True),
            False,
            "structured_output is required",
        ),
        (
            ModelCapabilities(reasoning=SupportStatus.UNSUPPORTED),
            RequestProfile(requires_reasoning=True),
            False,
            "reasoning is required",
        ),
        (
            ModelCapabilities(streaming=SupportStatus.UNSUPPORTED),
            RequestProfile(requires_streaming=True),
            False,
            "streaming is required",
        ),
    ],
)
def test_capability_hard_rejections(
    capabilities: ModelCapabilities,
    profile: RequestProfile,
    eligible: bool,
    reason: str,
) -> None:
    result = check_eligibility(capabilities, profile)
    assert result.eligible is eligible
    assert any(reason in item for item in result.reasons)


@pytest.mark.unit
def test_unknown_capabilities_follow_policy_and_price_is_not_a_capability() -> None:
    model = _model(pricing=Pricing())
    request = RequestProfile(input_modalities=frozenset({"text"}), requires_tools=True)
    rejected = check_eligibility(model, request)
    allowed = check_eligibility(model, request, missing_data_policy=MissingDataPolicy.ALLOW)
    assert rejected.eligible is False
    assert {"input_modalities", "tools"} == set(rejected.unknown_requirements)
    assert allowed.eligible is True
    assert allowed.reasons == ()
    assert check_eligibility(_model(), RequestProfile()).eligible is True


@pytest.mark.unit
def test_explicit_and_approximate_token_estimates_are_disclosed() -> None:
    estimator = FallbackTokenEstimator()
    approximate = estimator.estimate(model="model", prompt="abcdefgh")
    explicit = estimator.estimate(
        model="model", prompt="do not tokenize", explicit_input_tokens=88, expected_output_tokens=4
    )
    assert (approximate.input_tokens, approximate.exact) == (2, False)
    assert "Approximation" in approximate.notes[0]
    assert explicit.input_tokens == 88
    assert explicit.source == "explicit"
    assert explicit.exact is True


@pytest.mark.unit
def test_cost_components_cache_reasoning_fixed_fee_and_override() -> None:
    pricing = Pricing(
        components={
            key: PriceComponent(key=key, amount=Decimal(amount))
            for key, amount in {
                "prompt": "0.01",
                "completion": "0.02",
                "input_cache_read": "0.001",
                "input_cache_write": "0.003",
                "internal_reasoning": "0.004",
                "request": "0.5",
            }.items()
        },
        overrides=(
            PricingOverride(
                name="large-context",
                prompt_tokens_gte=100,
                prices={"prompt": PriceComponent(key="prompt", amount=Decimal("0.005"))},
            ),
        ),
    )
    estimate = estimate_cost(
        _model(pricing=pricing),
        TokenEstimate(input_tokens=100, output_tokens=40, source="explicit", exact=True),
        cached_input_read_tokens=10,
        cached_input_write_tokens=5,
        reasoning_tokens=5,
        unit_usage={"image": 2},
        now_utc=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert estimate.total == Decimal("1.67")
    assert {component.component for component in estimate.components} == {
        "prompt",
        "completion",
        "input_cache_read",
        "input_cache_write",
        "internal_reasoning",
        "request",
    }
    assert estimate.complete is False
    assert any("image" in assumption for assumption in estimate.assumptions)


@pytest.mark.unit
def test_missing_price_is_incomplete_but_free_price_is_explicit_zero() -> None:
    token_estimate = TokenEstimate(input_tokens=10, output_tokens=0, source="explicit", exact=True)
    missing = estimate_cost(_model(), token_estimate)
    free = estimate_cost(
        _model(
            pricing=Pricing(components={"prompt": PriceComponent(key="prompt", amount=Decimal(0))})
        ),
        token_estimate,
    )
    assert missing.total == 0
    assert missing.complete is False
    assert free.total == 0
    assert free.complete is True
    assert free.components[0].unit_price_usd == 0


@pytest.mark.unit
def test_cost_estimate_rejects_invalid_subusage_and_non_usd_price() -> None:
    token_estimate = TokenEstimate(input_tokens=10, output_tokens=0, source="explicit", exact=True)
    with pytest.raises(ValueError, match="cached input"):
        estimate_cost(
            _model(),
            token_estimate,
            cached_input_read_tokens=11,
        )
    foreign = estimate_cost(
        _model(
            pricing=Pricing(
                components={
                    "prompt": PriceComponent(key="prompt", amount=Decimal("0.01"), currency="EUR")
                }
            )
        ),
        token_estimate,
    )
    assert foreign.complete is False
    assert foreign.total == 0


@pytest.mark.unit
def test_cost_ceiling_rejects_known_partial_total_above_limit() -> None:
    model = _model(
        pricing=Pricing(components={"prompt": PriceComponent(key="prompt", amount=Decimal("0.2"))})
    )
    report = compare_models(
        [model],
        RequestProfile(explicit_input_tokens=10, max_cost_usd=Decimal("1")),
        FallbackTokenEstimator(),
        unit_usage={"image": 1},
        missing_data_policy=MissingDataPolicy.ALLOW,
    )
    result = report.candidates[0].eligibility
    assert result.eligible is False
    assert "cost_estimate" in result.unknown_requirements
    assert any("exceeds maximum" in reason for reason in result.reasons)


@pytest.mark.unit
@given(
    input_tokens=st.integers(min_value=0, max_value=100_000),
    output_tokens=st.integers(min_value=0, max_value=100_000),
    price=st.decimals(min_value=0, max_value=100, places=4, allow_nan=False),
)
def test_cost_is_nonnegative_and_increases_with_positive_usage(
    input_tokens: int, output_tokens: int, price: Decimal
) -> None:
    model = _model(
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=price),
                "completion": PriceComponent(key="completion", amount=price),
            }
        )
    )
    estimate = TokenEstimate(
        input_tokens=input_tokens, output_tokens=output_tokens, source="explicit", exact=True
    )
    cost = estimate_cost(model, estimate)
    more_input_cost = estimate_cost(
        model,
        estimate.model_copy(update={"input_tokens": input_tokens + 1}),
    )
    assert cost.total >= 0
    assert more_input_cost.total >= cost.total


@pytest.mark.unit
def test_builtin_and_custom_scenarios() -> None:
    scenario = workload_scenario("agent-step")
    assert scenario.profile.requires_tools is True
    assert scenario.profile.explicit_input_tokens == 2048
    custom = custom_workload_scenario("custom", input_tokens=3, output_tokens=4)
    assert custom.profile.minimum_context == 7
    with pytest.raises(ValueError, match="unknown workload"):
        workload_scenario("not-a-preset")
