"""Explainable hard-constraint matching for model capabilities."""

from __future__ import annotations

from enum import StrEnum
from typing import Optional, Union

from pydantic import BaseModel, ConfigDict

from model_compass.domain import ModelCapabilities, ModelProfile, RequestProfile, SupportStatus


class MissingDataPolicy(StrEnum):
    """How unknown data affects a hard requirement."""

    REJECT = "reject"
    ALLOW = "allow"


class EligibilityResult(BaseModel):
    """Capability eligibility and its human-readable explanation."""

    model_config = ConfigDict(frozen=True)

    eligible: bool
    reasons: tuple[str, ...] = ()
    unknown_requirements: tuple[str, ...] = ()


def check_eligibility(
    model: Union[ModelProfile, ModelCapabilities],
    request: RequestProfile,
    *,
    missing_data_policy: MissingDataPolicy = MissingDataPolicy.REJECT,
) -> EligibilityResult:
    """Apply only capability constraints; pricing is deliberately excluded."""
    capabilities = model.capabilities if isinstance(model, ModelProfile) else model
    rejected: list[str] = []
    unknown: list[str] = []

    if request.minimum_context is not None:
        if capabilities.context_length is None:
            unknown.append("context_length")
        elif capabilities.context_length < request.minimum_context:
            rejected.append(f"context length {capabilities.context_length} is below minimum {request.minimum_context}")
    if (
        request.expected_output_tokens is not None
        and capabilities.max_output_tokens is not None
        and capabilities.max_output_tokens < request.expected_output_tokens
    ):
        rejected.append(
            f"maximum output tokens {capabilities.max_output_tokens} is below expected {request.expected_output_tokens}"
        )
    elif request.expected_output_tokens is not None and capabilities.max_output_tokens is None:
        unknown.append("max_output_tokens")

    _check_modalities(
        "input",
        request.input_modalities,
        capabilities.input_modalities,
        rejected,
        unknown,
    )
    _check_modalities(
        "output",
        request.output_modalities,
        capabilities.output_modalities,
        rejected,
        unknown,
    )
    _check_flag("tools", request.requires_tools, capabilities.tools, rejected, unknown)
    _check_flag(
        "structured_output",
        request.requires_structured_output,
        capabilities.structured_output,
        rejected,
        unknown,
    )
    _check_flag("reasoning", request.requires_reasoning, capabilities.reasoning, rejected, unknown)
    _check_flag("streaming", request.requires_streaming, capabilities.streaming, rejected, unknown)

    if request.min_quality is not None:
        unknown.append("min_quality")
    if request.max_latency_ms is not None:
        unknown.append("max_latency_ms")
    if request.min_reliability is not None:
        unknown.append("min_reliability")

    reasons = list(rejected)
    if missing_data_policy == MissingDataPolicy.REJECT:
        reasons.extend(f"unknown capability: {requirement}" for requirement in unknown)
    return EligibilityResult(
        eligible=not reasons,
        reasons=tuple(reasons),
        unknown_requirements=tuple(dict.fromkeys(unknown)),
    )


def _check_modalities(
    direction: str,
    required: frozenset[str],
    supported: tuple[str, ...],
    rejected: list[str],
    unknown: list[str],
):
    """Record rejected or unknown modalities for one direction against a requirement."""
    if not required:
        return
    if not supported:
        unknown.append(f"{direction}_modalities")
        return
    unsupported = sorted(required - set(supported))
    rejected.extend(f"unsupported {direction} modality: {modality}" for modality in unsupported)


def _check_flag(
    name: str,
    required: Optional[bool],
    status: SupportStatus,
    rejected: list[str],
    unknown: list[str],
):
    """Record a rejected or unknown capability flag against a required flag."""
    if required is not True:
        return
    if status == SupportStatus.UNSUPPORTED:
        rejected.append(f"{name} is required but unsupported")
    elif status == SupportStatus.UNKNOWN:
        unknown.append(name)
