"""Deterministic request-aware cost estimation, selection, and Pareto analysis."""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.domain import ModelProfile, RequestProfile, SupportStatus
from model_compass.exceptions import NoEligibleModelError, SelectionError
from model_compass.metrics.task_observations import (
    MetricSummary,
    Observation,
    QualityEvidence,
    summarize_observations,
)
from model_compass.selection.constraints import (
    ConstraintResult,
    MaximumLatency,
    MinimumQuality,
    SelectionConstraint,
    request_constraints,
)
from model_compass.selection.evidence import (
    BenchmarkQualityProvider,
    MetricEvidence,
    QualityProvider,
)


class SelectionDataPolicy(BaseModel):
    """Explicitly control missing data and empirical sample thresholds."""

    model_config = ConfigDict(frozen=True)

    allow_unknown_capabilities: bool = False
    reject_missing_quality: bool = True
    reject_missing_latency: bool = True
    min_reliability_samples: int = Field(default=5, ge=1)
    min_latency_samples: int = Field(default=5, ge=1)
    allow_incomplete_cost_efficiency: bool = False
    wilson_z: Decimal = Decimal("1.96")

    @field_validator("wilson_z")
    @classmethod
    def _positive_finite_z(cls, value: Decimal) -> Decimal:
        if not value.is_finite() or value <= 0:
            raise ValueError("wilson_z must be finite and greater than zero")
        return value


class SelectionPolicy(StrEnum):
    """Supported transparent candidate ranking policies."""

    CHEAPEST = "cheapest"
    BEST = "best"
    FASTEST = "fastest"
    MOST_RELIABLE = "most-reliable"
    COST_EFFICIENT = "cost-efficient"


class ParetoObjective(StrEnum):
    """Built-in Pareto objective dimensions."""

    QUALITY = "quality"
    RELIABILITY = "reliability"
    COST = "cost"
    EXPECTED_COST = "expected_cost"
    LATENCY = "latency"


class ObjectiveDirection(StrEnum):
    """Direction in which an objective should be optimized."""

    MINIMIZE = "minimize"
    MAXIMIZE = "maximize"


class RequestCostEstimate(BaseModel):
    """Request cost estimate and explicit missing-price assumptions."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    amount_usd: Decimal | None
    missing_components: tuple[str, ...] = ()


class CandidateAssessment(BaseModel):
    """Eligibility and traceable evidence for one model considered by a selector."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    eligible: bool
    reasons: tuple[str, ...] = ()
    expected_cost_usd: Decimal | None = None
    quality: Decimal | None = None
    reliability: Decimal | None = None
    reliability_lower_bound: Decimal | None = None
    latency_ms: Decimal | None = None
    sample_size: int = 0
    quality_source: str | None = None
    quality_evidence: MetricEvidence[Decimal] | None = None
    latency_evidence: MetricEvidence[Decimal] | None = None
    reliability_evidence: MetricEvidence[Decimal] | None = None
    constraint_results: tuple[ConstraintResult, ...] = ()
    rankable: bool = True
    cost_efficiency_state: Literal["finite", "positive_infinity", "unknown"] = "unknown"
    rank: int | None = None
    pareto_member: bool | None = None


class SelectionResult(BaseModel):
    """Policy outcome, including rejections and missing-data diagnostics."""

    model_config = ConfigDict(frozen=True)

    policy: SelectionPolicy
    selected: CandidateAssessment | None
    ranked: tuple[CandidateAssessment, ...]
    assessments: tuple[CandidateAssessment, ...]
    rejection_counts: dict[str, int] = Field(default_factory=dict)
    assumptions: tuple[str, ...] = ()
    catalog_retrieved_at: datetime | None = None
    catalog_is_stale: bool = False

    def human_summary(self) -> str:
        """Describe the result using its primary objective and selected evidence."""
        if self.selected is None:
            reasons = ", ".join(f"{code}={count}" for code, count in self.rejection_counts.items())
            return f"No model was selected under {self.policy.value}." + (
                f" Rejections: {reasons}." if reasons else ""
            )
        selected = self.selected
        objective = {
            SelectionPolicy.CHEAPEST: f"expected cost ${selected.expected_cost_usd}",
            SelectionPolicy.BEST: (
                f"quality {selected.quality} from {selected.quality_source or 'unknown source'}"
            ),
            SelectionPolicy.FASTEST: (
                f"latency {selected.latency_ms}ms "
                f"({selected.latency_evidence.sample_count if selected.latency_evidence else 0} "
                "samples)"
            ),
            SelectionPolicy.MOST_RELIABLE: (
                f"Wilson lower bound {selected.reliability_lower_bound} "
                f"from {selected.sample_size} samples "
                f"(raw rate {selected.reliability})"
            ),
            SelectionPolicy.COST_EFFICIENT: (
                "positive-infinite quality/cost ratio"
                if selected.cost_efficiency_state == "positive_infinity"
                else f"quality/cost ratio {selected.quality}/{selected.expected_cost_usd}"
            ),
        }[self.policy]
        return f"Selected {selected.model_id} under {self.policy.value}: {objective}."

    def explain(self, model_id: str) -> str:
        """Explain selection, rejection, missing metrics, or ranking for one model."""
        candidate = next((item for item in self.assessments if item.model_id == model_id), None)
        if candidate is None:
            raise KeyError(f"model {model_id!r} was not assessed")
        if self.selected is not None and self.selected.model_id == model_id:
            return self.human_summary()
        failures = [result.message for result in candidate.constraint_results if not result.passed]
        failures.extend(candidate.reasons)
        details = "; ".join(dict.fromkeys(failures)) or "no hard constraint failed"
        if not candidate.eligible:
            return f"{model_id} was rejected: {details}."
        if not candidate.rankable:
            return f"{model_id} was not rankable under {self.policy.value}: {details}."
        if candidate.rank is not None:
            return (
                f"{model_id} ranked #{candidate.rank} under {self.policy.value}; "
                f"{self.selected.model_id if self.selected else 'no model'} ranked higher. "
                f"Evidence: {details}."
            )
        return f"{model_id} was eligible but not ranked under {self.policy.value}: {details}."


class ParetoResult(BaseModel):
    """Pareto members and optional explanations of dominated candidates."""

    model_config = ConfigDict(frozen=True)

    frontier: tuple[CandidateAssessment, ...]
    dominated_by: dict[str, tuple[str, ...]] = Field(default_factory=dict)


def estimate_request_cost(
    profile: ModelProfile, request: RequestProfile, *, now_utc: datetime | None = None
) -> RequestCostEstimate:
    """Estimate token cost using source per-token Decimal rates."""
    prices = profile.pricing.effective_components(
        prompt_tokens=request.explicit_input_tokens or 0, now_utc=now_utc
    )
    missing: list[str] = []
    amount = Decimal("0")
    for key, token_count in (
        ("prompt", request.explicit_input_tokens),
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
    return RequestCostEstimate(
        model_id=profile.identity.canonical_id,
        amount_usd=None if missing else amount,
        missing_components=tuple(missing),
    )


def select_model(
    profiles: Sequence[ModelProfile],
    request: RequestProfile,
    *,
    policy: SelectionPolicy = SelectionPolicy.BEST,
    objective: SelectionPolicy | str | None = None,
    observations: Sequence[Observation] = (),
    quality_evidence: Sequence[QualityEvidence] = (),
    quality_provider: QualityProvider | None = None,
    missing_data: SelectionDataPolicy | None = None,
    constraints: Sequence[SelectionConstraint] = (),
    min_quality: Decimal | None = None,
    max_cost: Decimal | None = None,
    max_cost_usd: Decimal | None = None,
    max_latency_ms: int | Decimal | None = None,
    min_reliability: Decimal | None = None,
    required_capabilities: Sequence[str] = (),
    minimum_context: int | None = None,
    allowed_model_ids: Sequence[str] = (),
    blocked_model_ids: Sequence[str] = (),
    allowed_gateways: Sequence[str] = (),
    blocked_gateways: Sequence[str] = (),
    allowed_providers: Sequence[str] = (),
    blocked_providers: Sequence[str] = (),
    raise_on_empty: bool = False,
    now_utc: datetime | None = None,
) -> SelectionResult:
    """Apply hard constraints, then deterministically rank request-aware candidates."""
    if objective is not None:
        try:
            policy = SelectionPolicy(objective)
        except ValueError as exc:
            raise SelectionError(f"unsupported selection policy: {objective}") from exc
    data_policy = missing_data or SelectionDataPolicy()
    task = request.task or "general"
    profiles_by_id = {profile.identity.canonical_id: profile for profile in profiles}
    summaries = {
        model_id: summarize_observations(model_id, task, list(observations))
        for model_id in profiles_by_id
    }
    provider = quality_provider or BenchmarkQualityProvider(quality_evidence)
    built_constraints = (
        *request_constraints(
            request,
            min_quality=min_quality,
            max_cost=max_cost if max_cost is not None else max_cost_usd,
            max_latency_ms=max_latency_ms,
            min_reliability=min_reliability,
            required_capabilities=required_capabilities,
            minimum_context=minimum_context,
            allowed_model_ids=allowed_model_ids,
            blocked_model_ids=blocked_model_ids,
            allowed_gateways=allowed_gateways,
            blocked_gateways=blocked_gateways,
            allowed_providers=allowed_providers,
            blocked_providers=blocked_providers,
        ),
        *constraints,
    )
    assessments = tuple(
        _assess(
            profile,
            request,
            summaries[profile.identity.canonical_id],
            provider,
            data_policy,
            built_constraints,
            now_utc=now_utc,
        )
        for profile in profiles
    )
    rankable = [
        item for item in assessments if item.eligible and _is_rankable(item, policy, data_policy)
    ]
    ordered = sorted(rankable, key=lambda item: _rank_key(item, policy, data_policy))
    ranked = tuple(
        item.model_copy(update={"rank": index}) for index, item in enumerate(ordered, start=1)
    )
    frontier_ids = {
        item.model_id
        for item in pareto_frontier(
            [item for item in assessments if item.eligible],
            {
                "quality": ObjectiveDirection.MAXIMIZE,
                "expected_cost": ObjectiveDirection.MINIMIZE,
                "latency": ObjectiveDirection.MINIMIZE,
                "reliability": ObjectiveDirection.MAXIMIZE,
            },
        )
    }
    complete_for_pareto = {
        item.model_id
        for item in assessments
        if item.eligible
        and all(
            _objective_value(item, name) is not None
            for name in ("quality", "expected_cost", "latency_ms", "reliability")
        )
    }
    final_assessments_list = []
    for item in assessments:
        rankability_result = _rankability_result(item, policy, data_policy)
        final_assessments_list.append(
            item.model_copy(
                update={
                    "rank": next(
                        (
                            index
                            for index, candidate in enumerate(ranked, start=1)
                            if candidate.model_id == item.model_id
                        ),
                        None,
                    ),
                    "pareto_member": (
                        item.model_id in frontier_ids
                        if item.model_id in complete_for_pareto
                        else None
                        if item.eligible
                        else False
                    ),
                    "rankable": rankability_result is None,
                    "reasons": (
                        (*item.reasons, rankability_result.message)
                        if rankability_result is not None
                        else item.reasons
                    ),
                    "constraint_results": (
                        (*item.constraint_results, rankability_result)
                        if rankability_result is not None
                        else item.constraint_results
                    ),
                }
            )
        )
    final_assessments = tuple(final_assessments_list)
    assessed_by_id = {item.model_id: item for item in final_assessments}
    ranked = tuple(assessed_by_id[item.model_id] for item in ranked)
    reasons = Counter(
        result.reason_code
        for item in final_assessments
        for result in item.constraint_results
        if not result.passed
    )
    result = SelectionResult(
        policy=policy,
        selected=ranked[0] if ranked else None,
        ranked=ranked,
        assessments=final_assessments,
        rejection_counts=dict(sorted(reasons.items())),
        assumptions=(
            f"Reliability ranking uses a Wilson lower confidence bound with "
            f"z={data_policy.wilson_z}; "
            "the default 1.96 is a two-sided 95% bound.",
            "Fastest uses observed p95 latency at or above the configured sample "
            "threshold; otherwise it uses the observed median.",
        ),
        catalog_retrieved_at=max((profile.retrieved_at for profile in profiles), default=None),
        catalog_is_stale=any(source.stale for profile in profiles for source in profile.sources),
    )
    if not ranked and raise_on_empty:
        raise NoEligibleModelError(result.rejection_counts)
    return result


def pareto_frontier(
    candidates: Sequence[CandidateAssessment],
    objectives: Sequence[ParetoObjective]
    | Mapping[str, ObjectiveDirection | Literal["minimize", "maximize"]],
    *,
    missing_value_policy: Literal["exclude", "raise"] = "exclude",
) -> tuple[CandidateAssessment, ...]:
    """Return a deterministic frontier; incomplete objective vectors are excluded by default."""
    return pareto_analysis(
        candidates, objectives, missing_value_policy=missing_value_policy
    ).frontier


def pareto_analysis(
    candidates: Sequence[CandidateAssessment],
    objectives: Sequence[ParetoObjective]
    | Mapping[str, ObjectiveDirection | Literal["minimize", "maximize"]],
    *,
    missing_value_policy: Literal["exclude", "raise"] = "exclude",
) -> ParetoResult:
    """Calculate the N-dimensional frontier and optionally explain dominance."""
    directions = _normalize_objectives(objectives)
    if not directions:
        raise SelectionError("at least one Pareto objective is required")
    if missing_value_policy not in {"exclude", "raise"}:
        raise SelectionError(f"unsupported missing-value policy: {missing_value_policy}")
    eligible = [item for item in candidates if item.eligible]
    complete = [
        item
        for item in eligible
        if all(_objective_value(item, name) is not None for name in directions)
    ]
    if missing_value_policy == "raise" and len(complete) != len(eligible):
        raise SelectionError("one or more eligible candidates have missing Pareto values")

    def dominates(left: CandidateAssessment, right: CandidateAssessment) -> bool:
        strictly_better = False
        for name, direction in directions.items():
            left_value = _objective_value(left, name)
            right_value = _objective_value(right, name)
            assert left_value is not None
            assert right_value is not None
            if direction == ObjectiveDirection.MAXIMIZE:
                if left_value < right_value:
                    return False
                strictly_better |= left_value > right_value
            else:
                if left_value > right_value:
                    return False
                strictly_better |= left_value < right_value
        return strictly_better

    frontier = tuple(
        sorted(
            (
                candidate
                for candidate in complete
                if not any(
                    other is not candidate
                    and other.model_id != candidate.model_id
                    and dominates(other, candidate)
                    for other in complete
                )
            ),
            key=lambda item: item.model_id,
        )
    )
    dominators = {
        candidate.model_id: tuple(
            sorted(
                other.model_id
                for other in complete
                if other.model_id != candidate.model_id and dominates(other, candidate)
            )
        )
        for candidate in complete
        if candidate not in frontier
    }
    return ParetoResult(frontier=frontier, dominated_by=dominators)


def wilson_lower_bound(
    successes: int, sample_count: int, *, z: Decimal = Decimal("1.96")
) -> Decimal:
    """Return the Wilson score lower bound for a binomial success proportion."""
    if sample_count < 1 or successes < 0 or successes > sample_count:
        raise ValueError("successes and sample_count must define a non-empty binomial sample")
    if z <= 0 or not z.is_finite():
        raise ValueError("z must be finite and greater than zero")
    n = Decimal(sample_count)
    p = Decimal(successes) / n
    z2 = z * z
    denominator = Decimal(1) + z2 / n
    center = p + z2 / (2 * n)
    margin = z * ((p * (1 - p) / n + z2 / (4 * n * n)).sqrt())
    return max(Decimal(0), (center - margin) / denominator)


def _assess(
    profile: ModelProfile,
    request: RequestProfile,
    summary: MetricSummary | None,
    quality_provider: QualityProvider,
    data_policy: SelectionDataPolicy,
    constraints: Sequence[SelectionConstraint],
    *,
    now_utc: datetime | None = None,
) -> CandidateAssessment:
    identity = profile.identity.canonical_id
    task = request.task or "general"
    capabilities = profile.capabilities
    reasons: list[str] = []
    _require_modalities(
        reasons, "input", request.input_modalities, capabilities.input_modalities, data_policy
    )
    _require_modalities(
        reasons, "output", request.output_modalities, capabilities.output_modalities, data_policy
    )
    for required, label, status in (
        (request.requires_tools, "tool calling", capabilities.tools),
        (request.requires_structured_output, "structured output", capabilities.structured_output),
        (request.requires_reasoning, "reasoning", capabilities.reasoning),
        (request.requires_streaming, "streaming", capabilities.streaming),
    ):
        if required:
            _require_support(reasons, label, status, data_policy)
    required_context = request.minimum_context
    counts = (request.explicit_input_tokens, request.expected_output_tokens)
    if any(count is not None for count in counts):
        token_context = sum(count or 0 for count in counts)
        required_context = max(required_context or 0, token_context)
    if required_context is not None and required_context > 0:
        if capabilities.context_length is None:
            if not data_policy.allow_unknown_capabilities:
                reasons.append("context length is unknown")
        elif capabilities.context_length < required_context:
            reasons.append(
                f"context length {capabilities.context_length} is below {required_context}"
            )
    if (
        request.expected_output_tokens is not None
        and capabilities.max_output_tokens is not None
        and capabilities.max_output_tokens < request.expected_output_tokens
    ):
        reasons.append(
            f"max output tokens {capabilities.max_output_tokens} is below "
            f"{request.expected_output_tokens}"
        )

    cost = estimate_request_cost(profile, request, now_utc=now_utc)
    quality_evidence = quality_provider.get_quality_evidence(identity, task)
    if quality_evidence is not None and quality_evidence.task not in (None, task):
        quality_evidence = None
    if quality_evidence is None and summary is not None and summary.mean_quality is not None:
        quality_evidence = MetricEvidence(
            value=summary.mean_quality,
            source="execution_observations",
            task=task,
            sample_count=summary.quality_sample_size,
            observed_at=summary.quality_observed_at,
            notes=("Sample-weighted mean of exact-task execution observations.",),
        )
    quality = quality_evidence.value if quality_evidence is not None else None

    reliability: Decimal | None = summary.reliability if summary is not None else None
    reliability_evidence: MetricEvidence[Decimal] | None = None
    lower_bound: Decimal | None = None
    if summary is not None:
        reliability_evidence = MetricEvidence(
            value=summary.reliability,
            source="execution_observations",
            task=task,
            sample_count=summary.sample_size,
            observed_at=summary.observed_at,
            notes=("Raw success rate; ranking uses a Wilson lower confidence bound.",),
        )
        lower_bound = wilson_lower_bound(
            summary.success_count, summary.sample_size, z=data_policy.wilson_z
        )

    latency: Decimal | None = None
    latency_evidence: MetricEvidence[Decimal] | None = None
    if summary is not None:
        if summary.sample_size >= data_policy.min_latency_samples:
            latency = Decimal(summary.p95_latency_ms)
            latency_note = "p95 nearest-rank latency selected because sample threshold was met."
            latency_source = "execution_observations:p95"
        else:
            latency = summary.median_latency_ms
            latency_note = "Median latency fallback because sample threshold was not met."
            latency_source = "execution_observations:median"
        latency_evidence = MetricEvidence(
            value=latency,
            source=latency_source,
            task=task,
            sample_count=summary.sample_size,
            observed_at=summary.observed_at,
            notes=(latency_note,),
        )
    assessment = CandidateAssessment(
        model_id=identity,
        eligible=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        expected_cost_usd=cost.amount_usd,
        quality=quality,
        reliability=reliability,
        reliability_lower_bound=lower_bound,
        latency_ms=latency,
        sample_size=(
            summary.sample_size
            if summary is not None
            else quality_evidence.sample_count
            if quality_evidence is not None and quality_evidence.sample_count is not None
            else 0
        ),
        quality_source=(
            "; ".join(quality_evidence.notes) or quality_evidence.source
            if quality_evidence is not None
            else None
        ),
        quality_evidence=quality_evidence,
        latency_evidence=latency_evidence,
        reliability_evidence=reliability_evidence,
        cost_efficiency_state=(
            "unknown"
            if quality is None or cost.amount_usd is None or (cost.amount_usd == 0 and quality == 0)
            else "positive_infinity"
            if cost.amount_usd == 0 and quality > 0
            else "finite"
        ),
    )
    capability_result = ConstraintResult(
        passed=assessment.eligible,
        reason_code="capability_requirements",
        message=(
            "capability requirements are satisfied"
            if assessment.eligible
            else "; ".join(assessment.reasons)
        ),
        evidence={
            "task": task,
            "input_modalities": tuple(sorted(request.input_modalities)),
            "output_modalities": tuple(sorted(request.output_modalities)),
        },
    )
    evaluated_constraints = []
    for constraint in constraints:
        result = constraint.evaluate(profile, assessment)
        if (
            isinstance(constraint, MinimumQuality)
            and assessment.quality is None
            and not data_policy.reject_missing_quality
        ):
            result = result.model_copy(
                update={
                    "passed": True,
                    "message": "quality evidence is missing and allowed by the data policy",
                }
            )
        elif (
            isinstance(constraint, MaximumLatency)
            and assessment.latency_evidence is None
            and not data_policy.reject_missing_latency
        ):
            result = result.model_copy(
                update={
                    "passed": True,
                    "message": "latency evidence is missing and allowed by the data policy",
                }
            )
        evaluated_constraints.append(result)
    constraint_results = (capability_result, *evaluated_constraints)
    failed = [item for item in constraint_results if not item.passed]
    missing_reasons: list[str] = []
    if quality is None:
        missing_reasons.append("quality evidence is missing")
        if request.min_quality is not None:
            missing_reasons.append(f"no quality evidence for task {task!r}")
    if summary is None:
        missing_reasons.append(f"no empirical observations for task {task!r}")
    if latency_evidence is None:
        missing_reasons.append("latency evidence is missing")
    if cost.amount_usd is None:
        missing_reasons.append(
            f"expected cost is unknown (missing {', '.join(cost.missing_components)})"
        )
    all_reasons = list(assessment.reasons)
    all_reasons.extend(item.message for item in failed)
    all_reasons.extend(missing_reasons)
    return assessment.model_copy(
        update={
            "eligible": assessment.eligible and not failed,
            "reasons": tuple(dict.fromkeys(all_reasons)),
            "constraint_results": constraint_results,
        }
    )


def _is_rankable(
    assessment: CandidateAssessment,
    policy: SelectionPolicy,
    data_policy: SelectionDataPolicy,
) -> bool:
    return _rankability_result(assessment, policy, data_policy) is None


def _rankability_result(
    assessment: CandidateAssessment,
    policy: SelectionPolicy,
    data_policy: SelectionDataPolicy,
) -> ConstraintResult | None:
    if policy == SelectionPolicy.CHEAPEST and assessment.expected_cost_usd is None:
        return ConstraintResult(
            passed=False,
            reason_code="cheapest_incomplete_cost",
            message="cheapest ranking requires a complete expected cost",
        )
    if (
        policy == SelectionPolicy.FASTEST
        and assessment.latency_evidence is None
        and data_policy.reject_missing_latency
    ):
        return ConstraintResult(
            passed=False,
            reason_code="fastest_missing_latency",
            message="fastest ranking requires observed latency evidence",
        )
    if policy == SelectionPolicy.MOST_RELIABLE and assessment.reliability_evidence is None:
        return ConstraintResult(
            passed=False,
            reason_code="most_reliable_missing_evidence",
            message="most-reliable ranking requires observed success evidence",
        )
    if policy != SelectionPolicy.COST_EFFICIENT:
        return None
    if assessment.quality is None:
        return ConstraintResult(
            passed=False,
            reason_code="cost_efficiency_missing_quality",
            message="cost-efficient ranking requires known quality evidence",
        )
    if assessment.expected_cost_usd is None and not data_policy.allow_incomplete_cost_efficiency:
        return ConstraintResult(
            passed=False,
            reason_code="cost_efficiency_incomplete_cost",
            message="cost-efficient ranking requires complete expected cost",
        )
    if assessment.expected_cost_usd == 0 and assessment.quality == 0:
        return ConstraintResult(
            passed=False,
            reason_code="cost_efficiency_zero_over_zero",
            message="cost-efficient ranking is undefined for zero quality and zero cost",
        )
    return None


def _rank_key(
    assessment: CandidateAssessment,
    policy: SelectionPolicy,
    data_policy: SelectionDataPolicy,
) -> tuple[object, ...]:
    identity = assessment.model_id
    reliability = assessment.reliability_lower_bound
    if policy == SelectionPolicy.CHEAPEST:
        return (
            assessment.expected_cost_usd is None,
            assessment.expected_cost_usd
            if assessment.expected_cost_usd is not None
            else Decimal(0),
            assessment.quality is None,
            -(assessment.quality or Decimal(0)),
            reliability is None,
            -(reliability or Decimal(0)),
            assessment.latency_ms is None,
            assessment.latency_ms if assessment.latency_ms is not None else Decimal(0),
            identity,
        )
    if policy == SelectionPolicy.BEST:
        return (
            assessment.quality is None,
            -(assessment.quality or Decimal(0)),
            assessment.expected_cost_usd is None,
            assessment.expected_cost_usd
            if assessment.expected_cost_usd is not None
            else Decimal(0),
            reliability is None,
            -(reliability or Decimal(0)),
            assessment.latency_ms is None,
            assessment.latency_ms if assessment.latency_ms is not None else Decimal(0),
            identity,
        )
    if policy == SelectionPolicy.FASTEST:
        return (
            assessment.latency_ms is None,
            assessment.latency_ms if assessment.latency_ms is not None else Decimal(0),
            identity,
        )
    if policy == SelectionPolicy.MOST_RELIABLE:
        return (
            assessment.sample_size < data_policy.min_reliability_samples or reliability is None,
            -(reliability or Decimal(0)),
            identity,
        )
    if policy == SelectionPolicy.COST_EFFICIENT:
        if assessment.quality is None or assessment.expected_cost_usd is None:
            return (True, Decimal(0), identity)
        if assessment.expected_cost_usd == 0:
            return (False, 0, -assessment.quality, identity)
        return (
            False,
            1,
            -(assessment.quality / assessment.expected_cost_usd),
            identity,
        )
    raise SelectionError(f"unsupported selection policy: {policy}")


def _normalize_objectives(
    objectives: Sequence[ParetoObjective]
    | Mapping[str, ObjectiveDirection | Literal["minimize", "maximize"]],
) -> dict[str, ObjectiveDirection]:
    if isinstance(objectives, Mapping):
        directions = {}
        for name, direction in objectives.items():
            try:
                normalized = ObjectiveDirection(direction)
            except ValueError as exc:
                raise SelectionError(f"unsupported Pareto direction: {direction}") from exc
            objective_name = _normalize_objective_name(name)
            if objective_name not in {"quality", "reliability", "expected_cost", "latency_ms"}:
                raise SelectionError(f"unsupported Pareto objective: {name}")
            if objective_name in directions:
                raise SelectionError(f"duplicate Pareto objective: {objective_name}")
            directions[objective_name] = normalized
        return directions
    result = {}
    for objective in objectives:
        name = _normalize_objective_name(objective.value)
        if name not in {"quality", "reliability", "expected_cost", "latency_ms"}:
            raise SelectionError(f"unsupported Pareto objective: {objective}")
        result[name] = (
            ObjectiveDirection.MAXIMIZE
            if name in {"quality", "reliability"}
            else ObjectiveDirection.MINIMIZE
        )
    return result


def _normalize_objective_name(name: str) -> str:
    aliases = {"cost": "expected_cost", "latency": "latency_ms"}
    return aliases.get(name, name)


def _objective_value(assessment: CandidateAssessment, objective: str) -> Decimal | None:
    reliability = assessment.reliability_lower_bound
    if reliability is None:
        reliability = assessment.reliability
    return {
        "quality": assessment.quality,
        "reliability": reliability,
        "expected_cost": assessment.expected_cost_usd,
        "latency_ms": assessment.latency_ms,
    }.get(objective)


def _require_modalities(
    reasons: list[str],
    direction: str,
    required: frozenset[str],
    available: tuple[str, ...],
    policy: SelectionDataPolicy,
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
    reasons: list[str], capability: str, status: SupportStatus, policy: SelectionDataPolicy
) -> None:
    if status == SupportStatus.UNSUPPORTED:
        reasons.append(f"{capability} is unsupported")
    elif status == SupportStatus.UNKNOWN and not policy.allow_unknown_capabilities:
        reasons.append(f"{capability} support is unknown")
