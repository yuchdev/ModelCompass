"""Provider-independent analysis results and deterministic serialization."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import ModelCapabilities, ModelProfile, RequestProfile
from model_compass.metrics import CostEstimate, TokenEstimate, TokenEstimator, estimate_cost
from model_compass.metrics.task_observations import Observation, QualityEvidence
from model_compass.selection.constraints import ConstraintResult, SelectionConstraint
from model_compass.selection.engine import (
    RequestCostEstimate,
    SelectionDataPolicy,
    SelectionPolicy,
    select_model,
)
from model_compass.selection.evidence import MetricEvidence, QualityProvider

from .capabilities import EligibilityResult, MissingDataPolicy, check_eligibility


class CandidateAnalysis(BaseModel):
    """Eligibility, usage, evidence, policy ranks, and capabilities for one model."""

    model_config = ConfigDict(frozen=True)

    model: ModelProfile
    eligibility: EligibilityResult
    token_estimate: TokenEstimate
    cost: CostEstimate
    capabilities: ModelCapabilities
    quality_evidence: Optional[MetricEvidence[Decimal]] = None
    latency_evidence: Optional[MetricEvidence[Decimal]] = None
    reliability_evidence: Optional[MetricEvidence[Decimal]] = None
    rank_by_policy: dict[str, int] = Field(default_factory=dict)
    selection_eligible: bool = True
    constraint_rejections: tuple[ConstraintResult, ...] = ()
    pareto_member: Optional[bool] = None


class ComparisonReport(BaseModel):
    """Stable serializable comparison of a request against model candidates."""

    model_config = ConfigDict(frozen=True)

    request: RequestProfile
    candidates: tuple[CandidateAnalysis, ...]
    selected_policy: Optional[SelectionPolicy] = None

    def to_json(self) -> str:
        """Serialize in stable key order and without formatting-dependent whitespace."""
        return json.dumps(
            self.model_dump(mode="json"),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        )


def compare_models(
    models: Sequence[ModelProfile],
    request: RequestProfile,
    token_estimator: TokenEstimator,
    *,
    prompt: Optional[str] = None,
    messages: Optional[Sequence[Mapping[str, object]]] = None,
    cached_input_read_tokens: int = 0,
    cached_input_write_tokens: int = 0,
    reasoning_tokens: Optional[int] = None,
    unit_usage: Optional[Mapping[str, Union[Decimal, int]]] = None,
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT,
    now_utc: Optional[datetime] = None,
    observations: Sequence[Observation] = (),
    quality_evidence: Sequence[QualityEvidence] = (),
    quality_provider: Optional[QualityProvider] = None,
    constraints: Sequence[SelectionConstraint] = (),
    policies: Sequence[SelectionPolicy] = tuple(SelectionPolicy),
    selected_policy: Optional[SelectionPolicy] = None,
) -> ComparisonReport:
    """Analyze candidates without invoking any model or provider service."""
    selected_policy = selected_policy or SelectionPolicy.BEST
    selection_policies = tuple(dict.fromkeys((*policies, selected_policy)))
    ordered_models = tuple(sorted(models, key=lambda item: item.identity.canonical_id))
    token_estimates = {
        model.identity.canonical_id: token_estimator.estimate(
            model=model.identity.model_id,
            prompt=prompt,
            messages=messages,
            explicit_input_tokens=request.explicit_input_tokens,
            expected_output_tokens=request.expected_output_tokens,
        )
        for model in ordered_models
    }
    cost_estimates = {
        model.identity.canonical_id: estimate_cost(
            model,
            token_estimates[model.identity.canonical_id],
            cached_input_read_tokens=cached_input_read_tokens,
            cached_input_write_tokens=cached_input_write_tokens,
            reasoning_tokens=reasoning_tokens,
            unit_usage=unit_usage,
            now_utc=now_utc,
        )
        for model in ordered_models
    }
    request_cost_estimates = {
        model_id: RequestCostEstimate(
            model_id=model_id,
            amount_usd=cost.total if cost.complete else None,
            known_amount_usd=cost.total,
            missing_components=tuple(cost.assumptions) if not cost.complete else (),
        )
        for model_id, cost in cost_estimates.items()
    }
    selection_data_policy = SelectionDataPolicy(
        allow_unknown_capabilities=missing_data_policy == MissingDataPolicy.ALLOW,
        reject_missing_quality=missing_data_policy == MissingDataPolicy.REJECT,
        reject_missing_latency=missing_data_policy == MissingDataPolicy.REJECT,
        reject_missing_cost=missing_data_policy == MissingDataPolicy.REJECT,
        reject_missing_reliability=missing_data_policy == MissingDataPolicy.REJECT,
    )
    policy_results = {
        policy: select_model(
            ordered_models,
            request,
            policy=policy,
            observations=observations,
            quality_evidence=quality_evidence,
            quality_provider=quality_provider,
            missing_data=selection_data_policy,
            request_cost_estimates=request_cost_estimates,
            constraints=constraints,
            now_utc=now_utc,
        )
        for policy in selection_policies
    }
    primary_result = policy_results.get(selected_policy)
    if primary_result is None and policy_results:
        primary_result = next(iter(policy_results.values()))
    assessments = {item.model_id: item for item in primary_result.assessments} if primary_result is not None else {}
    ranks = {
        policy.value: {item.model_id: index for index, item in enumerate(result.ranked, start=1)}
        for policy, result in policy_results.items()
    }
    candidates: list[CandidateAnalysis] = []
    for model in ordered_models:
        token_estimate = token_estimates[model.identity.canonical_id]
        cost = cost_estimates[model.identity.canonical_id]
        eligibility = check_eligibility(
            model,
            request,
            missing_data_policy=missing_data_policy,
        )
        if request.max_cost_usd is not None:
            reasons = list(eligibility.reasons)
            unknown = list(eligibility.unknown_requirements)
            eligible = eligibility.eligible
            if not cost.complete:
                unknown.append("cost_estimate")
            if cost.total > request.max_cost_usd:
                reasons.append(f"estimated cost {cost.total} USD exceeds maximum {request.max_cost_usd} USD")
                eligible = False
            elif not cost.complete:
                if missing_data_policy == MissingDataPolicy.REJECT:
                    reasons.append("cost ceiling cannot be verified because pricing is incomplete")
                    eligible = False
            eligibility = EligibilityResult(
                eligible=eligible,
                reasons=tuple(reasons),
                unknown_requirements=tuple(dict.fromkeys(unknown)),
            )
        candidates.append(
            CandidateAnalysis(
                model=model,
                eligibility=eligibility,
                token_estimate=token_estimate,
                cost=cost,
                capabilities=model.capabilities,
                quality_evidence=(
                    assessments[model.identity.canonical_id].quality_evidence
                    if model.identity.canonical_id in assessments
                    else None
                ),
                latency_evidence=(
                    assessments[model.identity.canonical_id].latency_evidence
                    if model.identity.canonical_id in assessments
                    else None
                ),
                reliability_evidence=(
                    assessments[model.identity.canonical_id].reliability_evidence
                    if model.identity.canonical_id in assessments
                    else None
                ),
                rank_by_policy={
                    policy: values[model.identity.canonical_id]
                    for policy, values in ranks.items()
                    if model.identity.canonical_id in values
                },
                selection_eligible=(
                    assessments[model.identity.canonical_id].eligible
                    if model.identity.canonical_id in assessments
                    else False
                ),
                constraint_rejections=(
                    tuple(
                        result
                        for result in assessments[model.identity.canonical_id].constraint_results
                        if not result.passed
                    )
                    if model.identity.canonical_id in assessments
                    else ()
                ),
                pareto_member=(
                    assessments[model.identity.canonical_id].pareto_member
                    if model.identity.canonical_id in assessments
                    else None
                ),
            )
        )
    return ComparisonReport(
        request=request,
        candidates=tuple(candidates),
        selected_policy=selected_policy,
    )
