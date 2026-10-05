from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from model_compass.domain import (
    ModelCapabilities,
    ModelEndpoint,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
    SupportStatus,
)
from model_compass.exceptions import NoEligibleModelError
from model_compass.metrics import Observation, QualityEvidence
from model_compass.selection import (
    CandidateAssessment,
    GatewayProviderAllowBlock,
    InMemoryQualityProvider,
    MaximumExpectedCost,
    MaximumLatency,
    MetricEvidence,
    MinimumContext,
    MinimumQuality,
    MinimumReliability,
    ModelIdAllowBlock,
    ObjectiveDirection,
    RequiredCapabilities,
    SelectionDataPolicy,
    SelectionPolicy,
    pareto_analysis,
    pareto_frontier,
    select_model,
    wilson_lower_bound,
)


def _profile(
    name: str,
    *,
    prompt_price: str = "0.000001",
    completion_price: str = "0.000002",
) -> ModelProfile:
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id=name, canonical_id=f"test:{name}"),
        capabilities=ModelCapabilities(
            context_length=100_000,
            max_output_tokens=20_000,
            input_modalities=("text",),
            output_modalities=("text",),
            tools=SupportStatus.SUPPORTED,
            structured_output=SupportStatus.SUPPORTED,
            reasoning=SupportStatus.SUPPORTED,
            streaming=SupportStatus.SUPPORTED,
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal(prompt_price)),
                "completion": PriceComponent(key="completion", amount=Decimal(completion_price)),
            }
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


def _observation(
    model_id: str,
    *,
    success: bool = True,
    latency: int = 10,
    quality: str | None = None,
) -> Observation:
    return Observation(
        model_id=model_id,
        task="task",
        succeeded=success,
        latency_ms=latency,
        quality_score=Decimal(quality) if quality is not None else None,
    )


@pytest.mark.unit
def test_wilson_bound_penalizes_small_samples_and_converges() -> None:
    one_of_one = wilson_lower_bound(1, 1)
    nine_ninety_nine_of_thousand = wilson_lower_bound(999, 1000)
    assert Decimal("0.20") < one_of_one < Decimal("0.21")
    assert Decimal("0.99") < nine_ninety_nine_of_thousand < Decimal("1")
    assert wilson_lower_bound(1000, 1000) > Decimal("0.99")
    assert wilson_lower_bound(1, 1) < wilson_lower_bound(999, 1000)
    with pytest.raises(ValueError, match="non-empty"):
        wilson_lower_bound(0, 0)


@pytest.mark.unit
def test_most_reliable_ranks_large_sample_over_perfect_single_observation() -> None:
    profiles = [_profile("one"), _profile("many")]
    observations = [_observation("test:one")]
    observations.extend(_observation("test:many", success=index < 999) for index in range(1000))
    result = select_model(
        profiles,
        RequestProfile(task="task", explicit_input_tokens=10, expected_output_tokens=10),
        policy=SelectionPolicy.MOST_RELIABLE,
        observations=observations,
    )
    assert result.selected is not None
    assert result.selected.model_id == "test:many"
    one = next(item for item in result.assessments if item.model_id == "test:one")
    assert one.reliability == Decimal(1)
    assert one.reliability_lower_bound == wilson_lower_bound(1, 1)
    assert result.selected.reliability_evidence is not None
    assert result.selected.reliability_evidence.sample_count == 1000


@pytest.mark.unit
def test_constraints_precede_ranking_and_empty_error_has_reason_counts() -> None:
    profile = _profile("blocked")
    evidence = InMemoryQualityProvider(
        {
            "test:blocked": MetricEvidence(
                value=Decimal("0.95"),
                source="synthetic",
                task="task",
                sample_count=10,
            )
        }
    )
    result = select_model(
        [profile],
        RequestProfile(task="task", explicit_input_tokens=10, expected_output_tokens=10),
        quality_provider=evidence,
        observations=[_observation("test:blocked", latency=20)],
        min_quality=Decimal("0.9"),
        max_latency_ms=500,
        allowed_model_ids=("test:other",),
        minimum_context=100,
    )
    assert result.selected is None
    assessment = result.assessments[0]
    assert assessment.eligible is False
    assert "was rejected" in result.explain("test:blocked")
    codes = {item.reason_code for item in assessment.constraint_results if not item.passed}
    assert codes == {"model_id_allow_block"}
    assert result.rejection_counts == {"model_id_allow_block": 1}
    with pytest.raises(NoEligibleModelError) as error:
        select_model(
            [profile],
            RequestProfile(explicit_input_tokens=10, expected_output_tokens=10),
            allowed_model_ids=("test:other",),
            raise_on_empty=True,
        )
    assert error.value.reason_counts == {"model_id_allow_block": 1}
    no_candidates = select_model([], RequestProfile())
    assert no_candidates.selected is None
    with pytest.raises(NoEligibleModelError) as no_candidate_error:
        select_model([], RequestProfile(), raise_on_empty=True)
    assert no_candidate_error.value.reason_counts == {}


@pytest.mark.unit
def test_objective_policies_do_not_rank_missing_primary_metrics() -> None:
    profile = _profile("missing", prompt_price="0", completion_price="0").model_copy(
        update={"pricing": Pricing()}
    )
    request = RequestProfile(explicit_input_tokens=1, expected_output_tokens=1)
    cheapest = select_model([profile], request, policy=SelectionPolicy.CHEAPEST)
    fastest = select_model([profile], request, policy=SelectionPolicy.FASTEST)
    reliable = select_model([profile], request, policy=SelectionPolicy.MOST_RELIABLE)
    assert cheapest.selected is None
    assert cheapest.rejection_counts == {"cheapest_incomplete_cost": 1}
    assert fastest.selected is None
    assert fastest.rejection_counts == {"fastest_missing_latency": 1}
    assert reliable.selected is None
    assert reliable.rejection_counts == {"most_reliable_missing_evidence": 1}


@pytest.mark.unit
def test_missing_metric_thresholds_can_be_allowed_explicitly() -> None:
    profile = _profile("unknown-metrics")
    request = RequestProfile(
        explicit_input_tokens=1,
        expected_output_tokens=1,
        min_quality=Decimal("0.8"),
        max_latency_ms=100,
    )
    default = select_model([profile], request)
    assert default.selected is None
    permissive = select_model(
        [profile],
        request,
        missing_data=SelectionDataPolicy(
            reject_missing_quality=False,
            reject_missing_latency=False,
        ),
    )
    assert permissive.selected is not None
    assert permissive.selected.model_id == "test:unknown-metrics"
    results = {
        result.reason_code: result.passed for result in permissive.assessments[0].constraint_results
    }
    assert results["minimum_quality"] is True
    assert results["maximum_latency"] is True


@pytest.mark.unit
def test_composable_constraints_report_pass_fail_evidence_and_validate_thresholds() -> None:
    profile = _profile("gateway").model_copy(
        update={
            "endpoints": (
                ModelEndpoint(
                    provider="test-provider",
                    endpoint_id="edge",
                    metadata={"gateway": "edge"},
                ),
            )
        }
    )
    profile_metrics = CandidateAssessment(
        model_id="test:gateway",
        eligible=True,
        expected_cost_usd=Decimal("1"),
        quality=Decimal("0.8"),
        reliability=Decimal("0.8"),
        latency_ms=Decimal("5"),
        quality_evidence=MetricEvidence(
            value=Decimal("0.8"), source="test", task="task", sample_count=5
        ),
        reliability_evidence=MetricEvidence(
            value=Decimal("0.8"), source="observations", task="task", sample_count=5
        ),
        latency_evidence=MetricEvidence(
            value=Decimal("5"), source="p95", task="task", sample_count=5
        ),
    )
    passing = (
        MinimumQuality(Decimal("0.8")),
        MaximumExpectedCost(Decimal("1")),
        MaximumLatency(5),
        MinimumReliability(Decimal("0.8")),
        RequiredCapabilities(("tools",)),
        MinimumContext(100),
        ModelIdAllowBlock(allowed=("test:gateway",)),
        GatewayProviderAllowBlock(allowed_gateways=("edge",), allowed_providers=("test-provider",)),
    )
    assert all(item.evaluate(profile, profile_metrics).passed for item in passing)
    failing = (
        MinimumQuality(Decimal("0.9")),
        MaximumExpectedCost(Decimal("0.5")),
        MaximumLatency(4),
        MinimumReliability(Decimal("0.9")),
        RequiredCapabilities(("image",)),
        MinimumContext(200_000),
        ModelIdAllowBlock(blocked=("test:gateway",)),
        GatewayProviderAllowBlock(blocked_gateways=("edge",)),
    )
    results = [item.evaluate(profile, profile_metrics) for item in failing]
    assert all(not item.passed for item in results)
    assert {item.reason_code for item in results} == {
        "minimum_quality",
        "maximum_expected_cost",
        "maximum_latency",
        "minimum_reliability",
        "required_capabilities",
        "minimum_context",
        "model_id_allow_block",
        "gateway_provider_allow_block",
    }
    with pytest.raises(ValueError, match="minimum quality"):
        MinimumQuality(Decimal("1.1"))
    with pytest.raises(ValueError, match="maximum expected cost"):
        MaximumExpectedCost(Decimal("-1"))
    with pytest.raises(ValueError, match="maximum latency"):
        MaximumLatency(-1)
    with pytest.raises(ValueError, match="minimum context"):
        MinimumContext(-1)


@pytest.mark.unit
def test_all_policies_have_deterministic_tie_breaks_and_zero_cost_state() -> None:
    profiles = [_profile("z"), _profile("a")]
    observations = [
        _observation("test:z", latency=20, quality="0.8"),
        _observation("test:a", latency=20, quality="0.8"),
    ]
    request = RequestProfile(task="task", explicit_input_tokens=10, expected_output_tokens=10)
    cheapest = select_model(
        profiles,
        request,
        policy=SelectionPolicy.CHEAPEST,
        observations=observations,
    )
    assert cheapest.selected is not None
    assert cheapest.selected.model_id == "test:a"
    assert "Selected test:a under cheapest" in cheapest.human_summary()
    assert "ranked #2 under cheapest" in cheapest.explain("test:z")
    objective_alias = select_model(
        profiles,
        request,
        objective="cheapest",
        observations=observations,
    )
    assert objective_alias.selected == cheapest.selected
    free = _profile("free", prompt_price="0", completion_price="0")
    free_observation = _observation("test:free", latency=20, quality="0.8")
    efficient = select_model(
        [*profiles, free],
        request,
        policy=SelectionPolicy.COST_EFFICIENT,
        observations=[*observations, free_observation],
    )
    assert efficient.selected is not None
    assert efficient.selected.model_id == "test:free"
    zero = next(item for item in efficient.assessments if item.model_id == "test:free")
    assert zero.expected_cost_usd == 0
    assert efficient.selected.cost_efficiency_state == "positive_infinity"
    zero_quality = select_model(
        [free],
        request,
        policy=SelectionPolicy.COST_EFFICIENT,
        observations=[_observation("test:free", quality="0")],
    )
    assert zero_quality.selected is None
    assert zero_quality.assessments[0].cost_efficiency_state == "unknown"
    assert zero_quality.rejection_counts == {"cost_efficiency_zero_over_zero": 1}
    incomplete = select_model(
        [_profile("incomplete").model_copy(update={"pricing": Pricing()})],
        request,
        policy=SelectionPolicy.COST_EFFICIENT,
        observations=[_observation("test:incomplete", quality="0.8")],
    )
    assert incomplete.selected is None
    assert incomplete.assessments[0].rankable is False
    assert incomplete.assessments[0].cost_efficiency_state == "unknown"


@pytest.mark.unit
def test_policy_tie_breakers_use_quality_cost_latency_and_canonical_id() -> None:
    request = RequestProfile(task="task", explicit_input_tokens=10, expected_output_tokens=10)
    best_profiles = [
        _profile("best-a"),
        _profile("best-b", prompt_price="0.000002", completion_price="0.000002"),
    ]
    best_observations = [
        _observation(model_id, success=success, latency=latency, quality="0.9")
        for model_id, success_count, latency in (
            ("test:best-a", 4, 20),
            ("test:best-b", 5, 1),
        )
        for index in range(5)
        for success in (index < success_count,)
    ]
    best = select_model(
        best_profiles,
        request,
        policy=SelectionPolicy.BEST,
        observations=best_observations,
    )
    assert best.selected is not None
    assert best.selected.model_id == "test:best-a"

    cheap_profiles = [_profile("cheap-a"), _profile("cheap-z")]
    cheap_observations = [
        _observation("test:cheap-a", quality="0.8"),
        _observation("test:cheap-z", quality="0.9"),
    ]
    cheapest = select_model(
        cheap_profiles,
        request,
        policy=SelectionPolicy.CHEAPEST,
        observations=cheap_observations,
    )
    assert cheapest.selected is not None
    assert cheapest.selected.model_id == "test:cheap-z"

    tied_profiles = [_profile("tie-b"), _profile("tie-a")]
    tied_observations = [
        _observation(model_id, latency=5)
        for model_id in ("test:tie-b", "test:tie-a")
        for _ in range(5)
    ]
    fastest = select_model(
        tied_profiles,
        request,
        policy=SelectionPolicy.FASTEST,
        observations=tied_observations,
    )
    most_reliable = select_model(
        tied_profiles,
        request,
        policy=SelectionPolicy.MOST_RELIABLE,
        observations=tied_observations,
    )
    assert fastest.selected is not None
    assert fastest.selected.model_id == "test:tie-a"
    assert fastest.selected.latency_evidence is not None
    assert fastest.selected.latency_evidence.source.endswith(":p95")
    assert most_reliable.selected is not None
    assert most_reliable.selected.model_id == "test:tie-a"

    efficient_profiles = [
        _profile("efficient-a", prompt_price="0.000001", completion_price="0.000001"),
        _profile("efficient-b", prompt_price="0.000002", completion_price="0.000002"),
    ]
    efficient_evidence = [
        QualityEvidence(
            model_id="test:efficient-a",
            task="task",
            quality_score=Decimal("0.5"),
            sample_size=1,
            source="test",
            evaluator_type="exact",
        ),
        QualityEvidence(
            model_id="test:efficient-b",
            task="task",
            quality_score=Decimal("1"),
            sample_size=1,
            source="test",
            evaluator_type="exact",
        ),
    ]
    efficient = select_model(
        efficient_profiles,
        request,
        policy=SelectionPolicy.COST_EFFICIENT,
        quality_evidence=efficient_evidence,
    )
    assert efficient.selected is not None
    assert efficient.selected.model_id == "test:efficient-a"


@pytest.mark.unit
def test_pareto_mapping_dominance_duplicates_and_missing_policy() -> None:
    candidates = [
        CandidateAssessment(
            model_id="tradeoff-a",
            eligible=True,
            quality=Decimal("0.8"),
            expected_cost_usd=Decimal("2"),
        ),
        CandidateAssessment(
            model_id="tradeoff-b",
            eligible=True,
            quality=Decimal("0.9"),
            expected_cost_usd=Decimal("3"),
        ),
        CandidateAssessment(
            model_id="dominated",
            eligible=True,
            quality=Decimal("0.7"),
            expected_cost_usd=Decimal("4"),
        ),
        CandidateAssessment(
            model_id="copy",
            eligible=True,
            quality=Decimal("0.8"),
            expected_cost_usd=Decimal("2"),
        ),
        CandidateAssessment(model_id="unknown", eligible=True, quality=Decimal("1")),
    ]
    objectives = {
        "quality": ObjectiveDirection.MAXIMIZE,
        "expected_cost": ObjectiveDirection.MINIMIZE,
    }
    result = pareto_analysis(candidates, objectives)
    assert [item.model_id for item in result.frontier] == [
        "copy",
        "tradeoff-a",
        "tradeoff-b",
    ]
    assert result.dominated_by["dominated"] == ("copy", "tradeoff-a", "tradeoff-b")
    assert [item.model_id for item in pareto_frontier(list(reversed(candidates)), objectives)] == [
        "copy",
        "tradeoff-a",
        "tradeoff-b",
    ]
    with pytest.raises(ValueError, match="missing Pareto"):
        pareto_frontier(candidates, objectives, missing_value_policy="raise")


@given(
    points=st.lists(
        st.tuples(st.integers(0, 100), st.integers(0, 100)),
        min_size=1,
        max_size=20,
    )
)
@pytest.mark.unit
def test_pareto_frontier_has_no_dominated_member(points: list[tuple[int, int]]) -> None:
    candidates = [
        CandidateAssessment(
            model_id=str(index),
            eligible=True,
            quality=Decimal(quality),
            expected_cost_usd=Decimal(cost),
        )
        for index, (quality, cost) in enumerate(points)
    ]
    frontier = pareto_frontier(
        candidates,
        {
            "quality": ObjectiveDirection.MAXIMIZE,
            "expected_cost": ObjectiveDirection.MINIMIZE,
        },
    )
    for candidate in frontier:
        assert candidate.quality is not None
        assert candidate.expected_cost_usd is not None
        for other in frontier:
            assert other.quality is not None
            assert other.expected_cost_usd is not None
            if other.model_id != candidate.model_id:
                assert not (
                    other.quality >= candidate.quality
                    and other.expected_cost_usd <= candidate.expected_cost_usd
                    and (
                        other.quality > candidate.quality
                        or other.expected_cost_usd < candidate.expected_cost_usd
                    )
                )


@given(
    points=st.lists(
        st.tuples(st.integers(1, 100), st.integers(0, 100)),
        min_size=1,
        max_size=20,
    )
)
@pytest.mark.unit
def test_adding_a_strictly_dominated_point_preserves_existing_frontier(
    points: list[tuple[int, int]],
) -> None:
    candidates = [
        CandidateAssessment(
            model_id=f"m{index}",
            eligible=True,
            quality=Decimal(quality),
            expected_cost_usd=Decimal(cost),
        )
        for index, (quality, cost) in enumerate(points)
    ]
    original = {
        item.model_id
        for item in pareto_frontier(
            candidates,
            {
                "quality": ObjectiveDirection.MAXIMIZE,
                "expected_cost": ObjectiveDirection.MINIMIZE,
            },
        )
    }
    quality, cost = points[0]
    dominated = CandidateAssessment(
        model_id="new-dominated",
        eligible=True,
        quality=Decimal(quality - 1),
        expected_cost_usd=Decimal(cost + 1),
    )
    expanded = {
        item.model_id
        for item in pareto_frontier(
            [*candidates, dominated],
            {
                "quality": ObjectiveDirection.MAXIMIZE,
                "expected_cost": ObjectiveDirection.MINIMIZE,
            },
        )
    }
    assert original <= expanded


@given(
    qualities=st.lists(
        st.decimals(min_value="0", max_value="1", places=2, allow_nan=False),
        min_size=1,
        max_size=8,
    )
)
@pytest.mark.unit
def test_selector_always_returns_an_eligible_assessment(qualities: list[Decimal]) -> None:
    profiles = [_profile(f"m{index}") for index in range(len(qualities))]
    evidence = [
        QualityEvidence(
            model_id=profile.identity.canonical_id,
            task="task",
            quality_score=quality,
            sample_size=1,
            source="hypothesis",
            evaluator_type="exact",
        )
        for profile, quality in zip(profiles, qualities, strict=True)
    ]
    result = select_model(
        profiles,
        RequestProfile(task="task", explicit_input_tokens=1, expected_output_tokens=1),
        policy=SelectionPolicy.BEST,
        quality_evidence=evidence,
    )
    assert result.selected is None or result.selected.eligible
    assert result.selected is None or result.selected in result.assessments
