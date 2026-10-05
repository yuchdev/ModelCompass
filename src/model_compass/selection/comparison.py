"""Provider-independent analysis results and deterministic serialization."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict

from model_compass.domain import ModelCapabilities, ModelProfile, RequestProfile
from model_compass.metrics import CostEstimate, TokenEstimate, TokenEstimator, estimate_cost

from .capabilities import EligibilityResult, MissingDataPolicy, check_eligibility


class CandidateAnalysis(BaseModel):
    """Eligibility, usage, pricing, and capabilities for one model."""

    model_config = ConfigDict(frozen=True)

    model: ModelProfile
    eligibility: EligibilityResult
    token_estimate: TokenEstimate
    cost: CostEstimate
    capabilities: ModelCapabilities


class ComparisonReport(BaseModel):
    """Stable serializable comparison of a request against model candidates."""

    model_config = ConfigDict(frozen=True)

    request: RequestProfile
    candidates: tuple[CandidateAnalysis, ...]

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
    prompt: str | None = None,
    messages: Sequence[Mapping[str, object]] | None = None,
    cached_input_read_tokens: int = 0,
    cached_input_write_tokens: int = 0,
    reasoning_tokens: int | None = None,
    unit_usage: Mapping[str, Decimal | int] | None = None,
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT,
    now_utc: datetime | None = None,
) -> ComparisonReport:
    """Analyze candidates without invoking any model or provider service."""
    candidates: list[CandidateAnalysis] = []
    for model in sorted(models, key=lambda item: item.identity.canonical_id):
        token_estimate = token_estimator.estimate(
            model=model.identity.model_id,
            prompt=prompt,
            messages=messages,
            explicit_input_tokens=request.explicit_input_tokens,
            expected_output_tokens=request.expected_output_tokens,
        )
        cost = estimate_cost(
            model,
            token_estimate,
            cached_input_read_tokens=cached_input_read_tokens,
            cached_input_write_tokens=cached_input_write_tokens,
            reasoning_tokens=reasoning_tokens,
            unit_usage=unit_usage,
            now_utc=now_utc,
        )
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
                reasons.append(
                    f"estimated cost {cost.total} USD exceeds maximum {request.max_cost_usd} USD"
                )
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
            )
        )
    return ComparisonReport(request=request, candidates=tuple(candidates))
