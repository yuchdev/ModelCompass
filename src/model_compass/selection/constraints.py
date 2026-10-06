"""Composable hard constraints for model selection."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Optional, Protocol, Union

from pydantic import BaseModel, ConfigDict, Field

from model_compass.domain import ModelProfile, RequestProfile, SupportStatus
from model_compass.selection.evidence import MetricEvidence


def _validated_decimal(value: Union[Decimal, int], name: str, *, maximum: Optional[Decimal] = None) -> Decimal:
    """Coerce a value to a finite, non-negative Decimal within an optional maximum."""
    result = value if isinstance(value, Decimal) else Decimal(value)
    if not result.is_finite() or result < 0 or (maximum is not None and result > maximum):
        upper = f" and at most {maximum}" if maximum is not None else ""
        raise ValueError(f"{name} must be finite, non-negative{upper}")
    return result


class ConstraintResult(BaseModel):
    """Machine-readable result of applying one selection constraint."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    reason_code: str
    message: str
    evidence: Mapping[str, object] = Field(default_factory=dict)


class CandidateMetrics(Protocol):
    """Selection metrics consumed by constraint evaluators."""

    expected_cost_usd: Optional[Decimal]
    quality: Optional[Decimal]
    reliability: Optional[Decimal]
    latency_ms: Optional[Decimal]
    quality_evidence: Optional[MetricEvidence[Decimal]]
    reliability_evidence: Optional[MetricEvidence[Decimal]]
    latency_evidence: Optional[MetricEvidence[Decimal]]


class SelectionConstraint(Protocol):
    """A reusable constraint evaluated independently for one candidate."""

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Return the constraint outcome for one candidate."""
        ...


class MinimumQuality:
    """Reject candidates whose quality is missing or below a minimum."""

    def __init__(self, value: Decimal):
        """Validate and store the minimum quality threshold."""
        self.value = _validated_decimal(value, "minimum quality", maximum=Decimal(1))

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate quality against the minimum threshold."""
        del profile
        evidence = metrics.quality_evidence
        passed = metrics.quality is not None and metrics.quality >= self.value
        return ConstraintResult(
            passed=passed,
            reason_code="minimum_quality",
            message=(
                f"quality {metrics.quality} meets minimum {self.value}"
                if passed
                else f"quality is missing or below minimum {self.value}"
            ),
            evidence={
                "value": metrics.quality,
                "minimum": self.value,
                "source": evidence.source if evidence else None,
            },
        )


class MaximumExpectedCost:
    """Reject candidates whose expected cost is missing or above a maximum."""

    def __init__(self, value: Decimal):
        """Validate and store the maximum expected cost threshold."""
        self.value = _validated_decimal(value, "maximum expected cost")

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate expected cost against the maximum threshold."""
        del profile
        passed = metrics.expected_cost_usd is not None and metrics.expected_cost_usd <= self.value
        return ConstraintResult(
            passed=passed,
            reason_code="maximum_expected_cost",
            message=(
                f"expected cost {metrics.expected_cost_usd} is within maximum {self.value}"
                if passed
                else f"expected cost is missing or exceeds maximum {self.value}"
            ),
            evidence={"value": metrics.expected_cost_usd, "maximum": self.value},
        )


class MaximumLatency:
    """Reject candidates whose latency is missing or above a maximum."""

    def __init__(self, value: Union[Decimal, int]):
        """Validate and store the maximum latency threshold."""
        self.value = _validated_decimal(value, "maximum latency")

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate latency against the maximum threshold."""
        del profile
        passed = metrics.latency_ms is not None and metrics.latency_ms <= self.value
        return ConstraintResult(
            passed=passed,
            reason_code="maximum_latency",
            message=(
                f"latency {metrics.latency_ms}ms is within maximum {self.value}ms"
                if passed
                else f"latency evidence is missing or latency exceeds maximum {self.value}ms"
            ),
            evidence={
                "value": metrics.latency_ms,
                "maximum": self.value,
                "source": metrics.latency_evidence.source if metrics.latency_evidence else None,
                "sample_count": (metrics.latency_evidence.sample_count if metrics.latency_evidence else None),
            },
        )


class MinimumReliability:
    """Reject candidates whose reliability is missing or below a minimum."""

    def __init__(self, value: Decimal):
        """Validate and store the minimum reliability threshold."""
        self.value = _validated_decimal(value, "minimum reliability", maximum=Decimal(1))

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate reliability against the minimum threshold."""
        del profile
        passed = metrics.reliability is not None and metrics.reliability >= self.value
        return ConstraintResult(
            passed=passed,
            reason_code="minimum_reliability",
            message=(
                f"reliability {metrics.reliability} meets minimum {self.value}"
                if passed
                else f"reliability is missing or below minimum {self.value}"
            ),
            evidence={
                "value": metrics.reliability,
                "minimum": self.value,
                "sample_count": (metrics.reliability_evidence.sample_count if metrics.reliability_evidence else None),
            },
        )


class RequiredCapabilities:
    """Reject candidates that do not support every required capability."""

    def __init__(self, capabilities: Sequence[str]):
        """Store the required capability names."""
        self.capabilities = tuple(capabilities)

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check that every required capability is supported by the candidate."""
        del metrics
        failed = [
            capability
            for capability in self.capabilities
            if getattr(profile.capabilities, capability, SupportStatus.UNKNOWN) != SupportStatus.SUPPORTED
        ]
        return ConstraintResult(
            passed=not failed,
            reason_code="required_capabilities",
            message="all required capabilities are supported"
            if not failed
            else (f"required capabilities are missing or unsupported: {', '.join(failed)}"),
            evidence={"required": self.capabilities, "failed": tuple(failed)},
        )


class MinimumContext:
    """Reject candidates whose context length is missing or below a minimum."""

    def __init__(self, value: int):
        """Validate and store the minimum context length."""
        if value < 0:
            raise ValueError("minimum context must be non-negative")
        self.value = value

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate context length against the minimum threshold."""
        del metrics
        context = profile.capabilities.context_length
        passed = context is not None and context >= self.value
        return ConstraintResult(
            passed=passed,
            reason_code="minimum_context",
            message=(
                f"context length {context} meets minimum {self.value}"
                if passed
                else f"context length is missing or below minimum {self.value}"
            ),
            evidence={"value": context, "minimum": self.value},
        )


class ModelIdAllowBlock:
    """Reject candidates outside an allow list or inside a block list of model IDs."""

    def __init__(self, *, allowed: Sequence[str] = (), blocked: Sequence[str] = ()):
        """Store the allowed and blocked model-ID sets."""
        self.allowed = frozenset(allowed)
        self.blocked = frozenset(blocked)

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate model ID against the allow and block lists."""
        del metrics
        model_id = profile.identity.canonical_id
        passed = (not self.allowed or model_id in self.allowed) and model_id not in self.blocked
        return ConstraintResult(
            passed=passed,
            reason_code="model_id_allow_block",
            message="model ID is allowed" if passed else f"model ID {model_id} is not allowed",
            evidence={"model_id": model_id},
        )


class GatewayProviderAllowBlock:
    """Reject candidates by gateway or provider allow and block lists."""

    def __init__(
        self,
        *,
        allowed_gateways: Sequence[str] = (),
        blocked_gateways: Sequence[str] = (),
        allowed_providers: Sequence[str] = (),
        blocked_providers: Sequence[str] = (),
    ):
        """Store the allowed and blocked gateway and provider sets."""
        self.allowed_gateways = frozenset(allowed_gateways)
        self.blocked_gateways = frozenset(blocked_gateways)
        self.allowed_providers = frozenset(allowed_providers)
        self.blocked_providers = frozenset(blocked_providers)

    def evaluate(self, profile: ModelProfile, metrics: CandidateMetrics) -> ConstraintResult:
        """Check the candidate gateways and providers against the allow and block lists."""
        del metrics
        provider = profile.identity.provider
        gateways = {
            str(endpoint.metadata["gateway"])
            for endpoint in profile.endpoints
            if endpoint.metadata.get("gateway") is not None
        }
        if not gateways:
            gateways = {endpoint.provider for endpoint in profile.endpoints}
        providers = {provider, *(endpoint.provider for endpoint in profile.endpoints)}
        passed = (
            (not self.allowed_gateways or bool(gateways & self.allowed_gateways))
            and not gateways & self.blocked_gateways
            and (not self.allowed_providers or bool(providers & self.allowed_providers))
            and not providers & self.blocked_providers
        )
        return ConstraintResult(
            passed=passed,
            reason_code="gateway_provider_allow_block",
            message="gateway/provider is allowed" if passed else "gateway/provider is blocked",
            evidence={"gateways": tuple(sorted(gateways)), "providers": tuple(sorted(providers))},
        )


def request_constraints(
    request: RequestProfile,
    *,
    min_quality: Optional[Decimal] = None,
    max_cost: Optional[Decimal] = None,
    max_latency_ms: Optional[Union[int, Decimal]] = None,
    min_reliability: Optional[Decimal] = None,
    required_capabilities: Sequence[str] = (),
    minimum_context: Optional[int] = None,
    allowed_model_ids: Sequence[str] = (),
    blocked_model_ids: Sequence[str] = (),
    allowed_gateways: Sequence[str] = (),
    blocked_gateways: Sequence[str] = (),
    allowed_providers: Sequence[str] = (),
    blocked_providers: Sequence[str] = (),
) -> tuple[SelectionConstraint, ...]:
    """Build the default hard constraints from request and explicit arguments."""
    quality = min_quality if min_quality is not None else request.min_quality
    cost = max_cost if max_cost is not None else request.max_cost_usd
    latency = max_latency_ms if max_latency_ms is not None else request.max_latency_ms
    reliability = min_reliability if min_reliability is not None else request.min_reliability
    constraints: list[SelectionConstraint] = []
    if quality is not None:
        constraints.append(MinimumQuality(quality))
    if cost is not None:
        constraints.append(MaximumExpectedCost(cost))
    if latency is not None:
        constraints.append(MaximumLatency(Decimal(latency)))
    if reliability is not None:
        constraints.append(MinimumReliability(reliability))
    if required_capabilities:
        constraints.append(RequiredCapabilities(tuple(dict.fromkeys(required_capabilities))))
    if minimum_context is not None:
        constraints.append(MinimumContext(minimum_context))
    if allowed_model_ids or blocked_model_ids:
        constraints.append(ModelIdAllowBlock(allowed=allowed_model_ids, blocked=blocked_model_ids))
    if any((allowed_gateways, blocked_gateways, allowed_providers, blocked_providers)):
        constraints.append(
            GatewayProviderAllowBlock(
                allowed_gateways=allowed_gateways,
                blocked_gateways=blocked_gateways,
                allowed_providers=allowed_providers,
                blocked_providers=blocked_providers,
            )
        )
    return tuple(constraints)
