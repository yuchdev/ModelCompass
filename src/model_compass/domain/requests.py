"""Typed workload requirements used by cost estimation and selection."""

from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.domain.models import parse_decimal


class RequestProfile(BaseModel):
    """Describe a workload and its hard constraints without storing prompt text."""

    model_config = ConfigDict(frozen=True)

    task: str = "general"
    input_modalities: frozenset[str] = frozenset({"text"})
    output_modalities: frozenset[str] = frozenset({"text"})
    estimated_input_tokens: int | None = Field(default=None, ge=0)
    expected_output_tokens: int | None = Field(default=None, ge=0)
    requires_tools: bool = False
    requires_structured_output: bool = False
    minimum_context: int | None = Field(default=None, ge=0)
    max_cost_usd: Decimal | None = None
    max_latency_ms: int | None = Field(default=None, ge=0)
    min_quality: Decimal | None = None

    @field_validator("input_modalities", "output_modalities")
    @classmethod
    def _normalize_modalities(cls, values: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(value.strip().lower() for value in values)
        if "" in normalized:
            raise ValueError("modalities must not contain empty values")
        return normalized

    @field_validator("task")
    @classmethod
    def _task_not_empty(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("task must not be empty")
        return value

    @field_validator("max_cost_usd", "min_quality", mode="before")
    @classmethod
    def _decimal_values(cls, value: object) -> Decimal | None:
        if value is None:
            return None
        return parse_decimal(value)

    @field_validator("max_cost_usd")
    @classmethod
    def _non_negative_cost(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (not value.is_finite() or value < 0):
            raise ValueError("max_cost_usd must be non-negative")
        return value

    @field_validator("min_quality")
    @classmethod
    def _quality_range(cls, value: Decimal | None) -> Decimal | None:
        if value is not None and (
            not value.is_finite() or not Decimal("0") <= value <= Decimal("1")
        ):
            raise ValueError("min_quality must be between 0 and 1")
        return value


class MissingDataPolicy(BaseModel):
    """Explicitly control how unknown capability and evidence data is treated."""

    model_config = ConfigDict(frozen=True)

    allow_unknown_capabilities: bool = False
    reject_missing_quality: bool = True
    reject_missing_latency: bool = True
