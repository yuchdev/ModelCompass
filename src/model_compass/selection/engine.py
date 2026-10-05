"""Deterministic request-aware cost estimation and model selection."""

from __future__ import annotations

from collections.abc import Sequence
from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from model_compass.domain import ModelProfile, SupportStatus
from model_compass.domain.requests import MissingDataPolicy, RequestProfile
from model_compass.exceptions import SelectionError
from model_compass.metrics.observations import (
    MetricSummary,
    Observation,
    QualityEvidence,
    summarize_observations,
    summarize_quality_evidence,
)


class SelectionPolicy(StrEnum):
    """Supported transparent candidate ranking policies."""

    CHEAPEST = "cheapest"
    BEST = "best"
    FASTEST = "fastest"
    MOST_RELIABLE = "most-reliable"
    COST_EFFICIENT = "cost-efficient"


class ParetoObjective(StrEnum):
    """Supported Pareto objective dimensions."""

    QUALITY = "quality"
    RELIABILITY = "reliability"
    COST = "cost"
    LATENCY = "latency"


class CostEstimate(BaseModel):
    """Request cost estimate and explicit missing-price assumptions."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    amount_usd: Decimal | None
    missing_components: tuple[str, ...] = ()


class CandidateAssessment(BaseModel):
    """Eligibility and evidence for one model considered by a selector."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    eligible: bool
    reasons: tuple[str, ...] = ()
    expected_cost_usd: Decimal | None = None
    quality: Decimal | None = None
    reliability: Decimal | None = None
    latency_ms: Decimal | None = None
    sample_size: int = 0
    quality_source: str | None = None


class SelectionResult(BaseModel):
    """Policy result with all decisions retained for explainability."""

    model_config = ConfigDict(frozen=True)

    policy: SelectionPolicy
    selected: CandidateAssessment | None
    ranked: tuple[CandidateAssessment, ...]
    assessments: tuple[CandidateAssessment, ...]


def estimate_cost(profile: ModelProfile, request: RequestProfile) -> CostEstimate:
    """Estimate token cost using source per-token Decimal rates."""
    prices = profile.pricing.effective_components(prompt_tokens=request.estimated_input_tokens or 0)
    missing: list[str] = []
    amount = Decimal("0")
    for key, token_count in (
        ("prompt", request.estimated_input_tokens),
        ("completion", request.expected_output_tokens),
    ):
        if token_count is None:
            missing.append(f"{key} token count")
            continue
        if token_count == 0:
            continue
        component = prices.get(key)
        if component is None:
            missing.append(key)
        else:
            amount += component.amount * token_count
    request_fee = prices.get("request")
    if request_fee is not None:
        amount += request_fee.amount
    return CostEstimate(
        model_id=profile.identity.canonical_id,
        amount_usd=None if missing else amount,
        missing_components=tuple(missing),
    )


def select_model(
    profiles: Sequence[ModelProfile],
    request: RequestProfile,
    *,
    policy: SelectionPolicy = SelectionPolicy.BEST,
    observations: Sequence[Observation] = (),
    quality_evidence: Sequence[QualityEvidence] = (),
    missing_data: MissingDataPolicy | None = None,
) -> SelectionResult:
    """Filter hard requirements, then rank eligible models under one policy."""
    missing_data = missing_data or MissingDataPolicy()
    summaries = {
        profile.identity.canonical_id: summarize_observations(
            profile.identity.canonical_id, request.task, list(observations)
        )
        for profile in profiles
    }
    evidence = list(quality_evidence)
    assessments = tuple(
        _assess(
            profile,
            request,
            summaries[profile.identity.canonical_id],
            evidence,
            missing_data,
        )
        for profile in profiles
    )
    eligible = [assessment for assessment in assessments if assessment.eligible]
    ranked = tuple(sorted(eligible, key=lambda item: _rank_key(item, policy)))
    return SelectionResult(
        policy=policy,
        selected=ranked[0] if ranked else None,
        ranked=ranked,
        assessments=assessments,
    )


def pareto_frontier(
    candidates: Sequence[CandidateAssessment],
    objectives: Sequence[ParetoObjective],
) -> tuple[CandidateAssessment, ...]:
    """Return non-dominated candidates, excluding unknown selected objectives."""
    if not objectives:
        raise SelectionError("at least one Pareto objective is required")

    complete = [
        item
        for item in candidates
        if item.eligible
        and all(_objective_value(item, objective) is not None for objective in objectives)
    ]

    def dominates(left: CandidateAssessment, right: CandidateAssessment) -> bool:
        no_worse = True
        strictly_better = False
        for objective in objectives:
            left_value = _objective_value(left, objective)
            right_value = _objective_value(right, objective)
            assert left_value is not None
            assert right_value is not None
            if objective in {ParetoObjective.QUALITY, ParetoObjective.RELIABILITY}:
                no_worse &= left_value >= right_value
                strictly_better |= left_value > right_value
            else:
                no_worse &= left_value <= right_value
                strictly_better |= left_value < right_value
        return no_worse and strictly_better

    frontier = [
        candidate
        for candidate in complete
        if not any(
            other.model_id != candidate.model_id and dominates(other, candidate)
            for other in complete
        )
    ]
    return tuple(sorted(frontier, key=lambda item: item.model_id))


def _assess(
    profile: ModelProfile,
    request: RequestProfile,
    summary: MetricSummary | None,
    quality_evidence: list[QualityEvidence],
    policy: MissingDataPolicy,
) -> CandidateAssessment:
    identity = profile.identity.canonical_id
    capabilities = profile.capabilities
    reasons: list[str] = []
    _require_modalities(
        reasons, "input", request.input_modalities, capabilities.input_modalities, policy
    )
    _require_modalities(
        reasons, "output", request.output_modalities, capabilities.output_modalities, policy
    )
    if request.requires_tools:
        _require_support(reasons, "tool calling", capabilities.tools, policy)
    if request.requires_structured_output:
        _require_support(reasons, "structured output", capabilities.structured_output, policy)

    required_context = request.minimum_context
    token_counts = (
        request.estimated_input_tokens,
        request.expected_output_tokens,
    )
    if any(count is not None for count in token_counts):
        token_context = sum(count or 0 for count in token_counts)
        required_context = max(required_context or 0, token_context)
    if required_context is not None and required_context > 0:
        if capabilities.context_length is None:
            if not policy.allow_unknown_capabilities:
                reasons.append("context length is unknown")
        elif capabilities.context_length < required_context:
            reasons.append(
                f"context length {capabilities.context_length} is below {required_context}"
            )

    if (
        request.expected_output_tokens
        and capabilities.max_output_tokens is not None
        and capabilities.max_output_tokens < request.expected_output_tokens
    ):
        reasons.append(
            f"max output tokens {capabilities.max_output_tokens} is below "
            f"{request.expected_output_tokens}"
        )

    cost = estimate_cost(profile, request)
    benchmark_quality = summarize_quality_evidence(identity, request.task, quality_evidence)
    quality = (
        benchmark_quality[0] if benchmark_quality else (summary.mean_quality if summary else None)
    )
    reliability = summary.reliability if summary else None
    latency = summary.mean_latency_ms if summary else None
    if request.max_cost_usd is not None:
        if cost.amount_usd is None:
            reasons.append(f"cost is unknown (missing {', '.join(cost.missing_components)})")
        elif cost.amount_usd > request.max_cost_usd:
            reasons.append(
                f"estimated cost {cost.amount_usd} exceeds budget {request.max_cost_usd}"
            )
    if request.min_quality is not None:
        if quality is None:
            if policy.reject_missing_quality:
                reasons.append(f"no quality evidence for task {request.task!r}")
        elif quality < request.min_quality:
            reasons.append(f"quality {quality} is below minimum {request.min_quality}")
    if request.max_latency_ms is not None:
        if latency is None:
            if policy.reject_missing_latency:
                reasons.append("latency evidence is missing")
        elif latency > request.max_latency_ms:
            reasons.append(f"latency {latency}ms exceeds limit {request.max_latency_ms}ms")

    if summary is None:
        reasons.append(f"no empirical observations for task {request.task!r}")
    elif quality is None:
        reasons.append("quality evidence is missing")
    if cost.amount_usd is None:
        reasons.append(f"expected cost is unknown (missing {', '.join(cost.missing_components)})")

    return CandidateAssessment(
        model_id=identity,
        eligible=not any(_is_rejection(reason) for reason in reasons),
        reasons=tuple(dict.fromkeys(reasons)),
        expected_cost_usd=cost.amount_usd,
        quality=quality,
        reliability=reliability,
        latency_ms=latency,
        sample_size=(
            benchmark_quality[1]
            if benchmark_quality is not None
            else summary.sample_size
            if summary
            else 0
        ),
        quality_source=(
            "; ".join(
                sorted(
                    {
                        f"{item.source}:{item.dataset or item.evaluator_type}"
                        for item in quality_evidence
                        if item.model_id == identity and item.task == request.task
                    }
                )
            )
            if benchmark_quality is not None
            else ("execution observations" if quality is not None else None)
        ),
    )


def _require_modalities(
    reasons: list[str],
    direction: str,
    required: frozenset[str],
    available: tuple[str, ...],
    policy: MissingDataPolicy,
) -> None:
    if not required:
        return
    if not available:
        if not policy.allow_unknown_capabilities:
            reasons.append(f"{direction} modalities are unknown")
        return
    missing = required - {item.lower() for item in available}
    if missing:
        reasons.append(f"unsupported {direction} modalities: {', '.join(sorted(missing))}")


def _require_support(
    reasons: list[str], capability: str, status: SupportStatus, policy: MissingDataPolicy
) -> None:
    if status == SupportStatus.UNSUPPORTED:
        reasons.append(f"{capability} is unsupported")
    elif status == SupportStatus.UNKNOWN and not policy.allow_unknown_capabilities:
        reasons.append(f"{capability} support is unknown")


def _is_rejection(reason: str) -> bool:
    return not reason.startswith(
        ("no empirical observations", "quality evidence is missing", "expected cost is unknown")
    )


def _rank_key(assessment: CandidateAssessment, policy: SelectionPolicy) -> tuple[object, ...]:
    identity = assessment.model_id
    if policy == SelectionPolicy.CHEAPEST:
        return (
            assessment.expected_cost_usd is None,
            assessment.expected_cost_usd or Decimal(0),
            identity,
        )
    if policy == SelectionPolicy.BEST:
        return (assessment.quality is None, -(assessment.quality or Decimal(0)), identity)
    if policy == SelectionPolicy.FASTEST:
        return (assessment.latency_ms is None, assessment.latency_ms or Decimal(0), identity)
    if policy == SelectionPolicy.MOST_RELIABLE:
        return (assessment.reliability is None, -(assessment.reliability or Decimal(0)), identity)
    if policy == SelectionPolicy.COST_EFFICIENT:
        if assessment.quality is None or assessment.expected_cost_usd is None:
            return (True, Decimal(0), identity)
        if assessment.expected_cost_usd == 0:
            return (False, 0, -assessment.quality, identity)
        return (False, 1, -(assessment.quality / assessment.expected_cost_usd), identity)
    raise SelectionError(f"unsupported selection policy: {policy}")


def _objective_value(assessment: CandidateAssessment, objective: ParetoObjective) -> Decimal | None:
    return {
        ParetoObjective.QUALITY: assessment.quality,
        ParetoObjective.RELIABILITY: assessment.reliability,
        ParetoObjective.COST: assessment.expected_cost_usd,
        ParetoObjective.LATENCY: assessment.latency_ms,
    }[objective]
