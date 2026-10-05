from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from model_compass.domain import (
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
    SupportStatus,
)
from model_compass.metrics import Observation, QualityEvidence, summarize_observations
from model_compass.selection import (
    CandidateAssessment,
    ParetoObjective,
    SelectionPolicy,
    estimate_cost,
    pareto_frontier,
    select_model,
)


def make_profile(
    model: str,
    *,
    prompt_price: str = "0.000001",
    completion_price: str = "0.000002",
    tools: SupportStatus = SupportStatus.SUPPORTED,
) -> ModelProfile:
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id=model, canonical_id=f"test:{model}"),
        capabilities=ModelCapabilities(
            context_length=100_000,
            input_modalities=("text",),
            output_modalities=("text",),
            tools=tools,
            structured_output=SupportStatus.SUPPORTED,
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal(prompt_price)),
                "completion": PriceComponent(key="completion", amount=Decimal(completion_price)),
            }
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


@pytest.mark.unit
def test_cost_estimation_uses_decimal_rates_and_missing_token_counts() -> None:
    profile = make_profile("cheap")
    request = RequestProfile(estimated_input_tokens=100, expected_output_tokens=20)

    estimate = estimate_cost(profile, request)
    assert estimate.amount_usd == Decimal("0.000140")
    assert estimate.missing_components == ()

    unknown = estimate_cost(profile, RequestProfile(estimated_input_tokens=100))
    assert unknown.amount_usd is None
    assert unknown.missing_components == ("completion token count",)

    free = make_profile("free", prompt_price="0", completion_price="0")
    assert estimate_cost(free, request).amount_usd == Decimal("0")


@pytest.mark.unit
def test_selection_enforces_capabilities_quality_and_cost() -> None:
    profile = make_profile("cheap")
    request = RequestProfile(
        task="code_review",
        estimated_input_tokens=10,
        expected_output_tokens=10,
        requires_tools=True,
        max_cost_usd=Decimal("0.0001"),
        min_quality=Decimal("0.8"),
    )
    rejected = select_model(
        [profile],
        request,
        observations=[
            Observation(
                model_id="test:cheap",
                task="general",
                succeeded=True,
                latency_ms=5,
                quality_score=Decimal("1"),
            )
        ],
    )
    assert rejected.selected is None
    assert "no quality evidence for task 'code_review'" in rejected.assessments[0].reasons

    accepted = select_model(
        [profile],
        request.model_copy(update={"max_cost_usd": Decimal("1")}),
        observations=[
            Observation(
                model_id="test:cheap",
                task="code_review",
                succeeded=True,
                latency_ms=5,
                quality_score=Decimal("0.9"),
            )
        ],
    )
    assert accepted.selected is not None
    assert accepted.selected.model_id == "test:cheap"


@pytest.mark.unit
def test_unknown_capabilities_and_missing_cost_are_not_hard_match() -> None:
    unknown = make_profile("unknown", tools=SupportStatus.UNKNOWN).model_copy(
        update={"capabilities": ModelCapabilities()}
    )
    request = RequestProfile(
        estimated_input_tokens=1,
        expected_output_tokens=1,
        requires_tools=True,
        minimum_context=50,
    )
    result = select_model([unknown], request)
    assert result.selected is None
    assert any("support is unknown" in reason for reason in result.assessments[0].reasons)
    assert any("context length is unknown" in reason for reason in result.assessments[0].reasons)

    unpriced = make_profile("unpriced").model_copy(update={"pricing": Pricing()})
    budgeted = select_model(
        [unpriced],
        request.model_copy(
            update={"requires_tools": False, "minimum_context": None, "max_cost_usd": Decimal("1")}
        ),
    )
    assert budgeted.selected is None


@pytest.mark.unit
def test_partial_token_estimates_still_require_known_context() -> None:
    unknown_context = make_profile("unknown-context").model_copy(
        update={
            "capabilities": ModelCapabilities(
                input_modalities=("text",), output_modalities=("text",)
            )
        }
    )
    request = RequestProfile(estimated_input_tokens=100)
    assert select_model([unknown_context], request).selected is None
    known = unknown_context.model_copy(
        update={
            "capabilities": ModelCapabilities(
                context_length=100,
                input_modalities=("text",),
                output_modalities=("text",),
            )
        }
    )
    assert select_model([known], request).selected is not None


@pytest.mark.unit
def test_policy_ranking_and_task_matched_summary() -> None:
    cheap = make_profile("cheap")
    quality = make_profile("quality", prompt_price="0.00001", completion_price="0.00001")
    observations = [
        Observation(
            model_id="test:cheap",
            task="general",
            succeeded=True,
            latency_ms=10,
            quality_score=Decimal("0.8"),
        ),
        Observation(
            model_id="test:cheap",
            task="code",
            succeeded=True,
            latency_ms=10,
            quality_score=Decimal("0.8"),
        ),
        Observation(
            model_id="test:quality",
            task="code",
            succeeded=True,
            latency_ms=5,
            quality_score=Decimal("0.95"),
        ),
    ]
    summary = summarize_observations("test:cheap", "code", observations)
    assert summary is not None
    assert summary.sample_size == 1
    assert summarize_observations("test:cheap", "missing", observations) is None

    req = RequestProfile(task="code", estimated_input_tokens=10, expected_output_tokens=10)
    by_cost = select_model(
        [cheap, quality], req, policy=SelectionPolicy.CHEAPEST, observations=observations
    )
    by_quality = select_model(
        [cheap, quality], req, policy=SelectionPolicy.BEST, observations=observations
    )
    by_latency = select_model(
        [cheap, quality], req, policy=SelectionPolicy.FASTEST, observations=observations
    )
    by_reliability = select_model(
        [cheap, quality], req, policy=SelectionPolicy.MOST_RELIABLE, observations=observations
    )
    efficient = select_model(
        [cheap, quality], req, policy=SelectionPolicy.COST_EFFICIENT, observations=observations
    )
    assert by_cost.selected is not None
    assert by_cost.selected.model_id == "test:cheap"
    assert by_quality.selected is not None
    assert by_quality.selected.model_id == "test:quality"
    assert by_latency.selected is not None
    assert by_latency.selected.model_id == "test:quality"
    assert by_reliability.selected is not None
    assert efficient.selected is not None


@pytest.mark.unit
def test_zero_cost_is_handled_as_best_cost_efficiency() -> None:
    free = make_profile("free", prompt_price="0", completion_price="0")
    paid = make_profile("paid")
    observations = [
        Observation(
            model_id="test:free",
            task="general",
            succeeded=True,
            latency_ms=1,
            quality_score=Decimal("0.5"),
        ),
        Observation(
            model_id="test:paid",
            task="general",
            succeeded=True,
            latency_ms=1,
            quality_score=Decimal("1"),
        ),
    ]
    result = select_model(
        [paid, free],
        RequestProfile(estimated_input_tokens=10, expected_output_tokens=10),
        policy=SelectionPolicy.COST_EFFICIENT,
        observations=observations,
    )
    assert result.selected is not None
    assert result.selected.model_id == "test:free"


@pytest.mark.unit
def test_missing_quality_threshold_and_latency_threshold_reject_by_default() -> None:
    profile = make_profile("no-evidence")
    req = RequestProfile(
        estimated_input_tokens=1,
        expected_output_tokens=1,
        min_quality=Decimal("0.5"),
        max_latency_ms=100,
    )
    result = select_model([profile], req)
    assert result.selected is None
    assert "latency evidence is missing" in result.assessments[0].reasons


@pytest.mark.unit
def test_benchmark_quality_evidence_is_weighted_and_task_scoped() -> None:
    profile = make_profile("tested")
    request = RequestProfile(
        task="code",
        estimated_input_tokens=2,
        expected_output_tokens=2,
        min_quality=Decimal("0.8"),
    )
    quality = [
        QualityEvidence(
            model_id="test:tested",
            task="code",
            quality_score=Decimal("0.9"),
            sample_size=9,
            source="benchmark",
            evaluator_type="exact",
            dataset="large",
        ),
        QualityEvidence(
            model_id="test:tested",
            task="code",
            quality_score=Decimal("0.1"),
            sample_size=1,
            source="benchmark",
            evaluator_type="exact",
            dataset="tiny",
        ),
        QualityEvidence(
            model_id="test:tested",
            task="general",
            quality_score=Decimal("0"),
            sample_size=10,
            source="benchmark",
            evaluator_type="exact",
        ),
    ]
    result = select_model([profile], request, quality_evidence=quality)
    assert result.selected is not None
    assert result.selected.quality == Decimal("0.82")
    assert result.selected.sample_size == 10
    assert result.selected.quality_source == "benchmark:large; benchmark:tiny"


@pytest.mark.unit
def test_request_rejects_non_finite_money_and_quality() -> None:
    with pytest.raises(ValueError, match="max_cost_usd"):
        RequestProfile(max_cost_usd=Decimal("NaN"))
    with pytest.raises(ValueError, match="min_quality"):
        RequestProfile(min_quality=Decimal("Infinity"))


@pytest.mark.unit
def test_pareto_frontier_uses_selected_objectives_and_excludes_unknowns() -> None:
    candidates = [
        CandidateAssessment(
            model_id="a", eligible=True, quality=Decimal("0.8"), expected_cost_usd=Decimal("2")
        ),
        CandidateAssessment(
            model_id="b", eligible=True, quality=Decimal("0.9"), expected_cost_usd=Decimal("3")
        ),
        CandidateAssessment(
            model_id="c", eligible=True, quality=Decimal("0.7"), expected_cost_usd=Decimal("4")
        ),
        CandidateAssessment(model_id="unknown", eligible=True, quality=Decimal("1")),
    ]
    frontier = pareto_frontier(candidates, [ParetoObjective.QUALITY, ParetoObjective.COST])
    assert [item.model_id for item in frontier] == ["a", "b"]
    with pytest.raises(ValueError, match="at least one"):
        pareto_frontier(candidates, [])
