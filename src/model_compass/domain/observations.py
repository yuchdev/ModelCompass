"""Provider-independent execution, benchmark, and quality evidence records."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _utc(value: datetime) -> datetime:
    """Return value normalized to UTC, requiring an explicit timezone."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


class Observation(BaseModel):
    """Measured execution data; storage applies its payload policy before saving."""

    model_config = ConfigDict(frozen=True)

    observation_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    model_id: str = Field(min_length=1)
    endpoint: Optional[str] = None
    gateway: Optional[str] = None
    provider: Optional[str] = None
    task: Optional[str] = None
    success: bool
    failure_category: Optional[str] = None
    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    cached_read_tokens: Optional[int] = Field(default=None, ge=0)
    cached_write_tokens: Optional[int] = Field(default=None, ge=0)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    estimated_cost: Optional[Decimal] = Field(default=None, ge=0)
    actual_cost: Optional[Decimal] = Field(default=None, ge=0)
    cost_source: Optional[str] = None
    latency_ms: Optional[Decimal] = Field(default=None, ge=0)
    time_to_first_token_ms: Optional[Decimal] = Field(default=None, ge=0)
    finish_reason: Optional[str] = None
    request_fingerprint: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    prompt: Optional[str] = None
    response: Optional[str] = None

    @field_validator("timestamp")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        """Normalize the observation timestamp to UTC."""
        return _utc(value)

    @field_validator("estimated_cost", "actual_cost", "latency_ms", "time_to_first_token_ms")
    @classmethod
    def _finite_decimal(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        """Reject non-finite numeric measurements."""
        if value is not None and not value.is_finite():
            raise ValueError("numeric measurements must be finite")
        return value


class BenchmarkRun(BaseModel):
    """Metadata for one reproducible benchmark execution."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    dataset_id: str = Field(min_length=1)
    dataset_version: Optional[str] = None
    dataset_hash: Optional[str] = None
    started_at: datetime
    ended_at: Optional[datetime] = None
    runner_version: Optional[str] = None
    configuration: dict[str, Any] = Field(default_factory=dict)
    status: str

    @field_validator("started_at", "ended_at")
    @classmethod
    def _normalize_timestamp(cls, value: Optional[datetime]) -> Optional[datetime]:
        """Normalize optional run timestamps to UTC."""
        return _utc(value) if value is not None else None

    @model_validator(mode="after")
    def _valid_interval(self) -> BenchmarkRun:
        """Reject runs whose end precedes their start."""
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("benchmark end cannot precede its start")
        return self


class BenchmarkResult(BaseModel):
    """One model's score for a case in a benchmark run."""

    model_config = ConfigDict(frozen=True)

    run_id: str = Field(min_length=1)
    case_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)
    score: Optional[Decimal] = None
    evaluator: Optional[str] = None
    cost: Optional[Decimal] = Field(default=None, ge=0)
    latency_ms: Optional[Decimal] = Field(default=None, ge=0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score", "cost", "latency_ms")
    @classmethod
    def _finite_decimal(cls, value: Optional[Decimal]) -> Optional[Decimal]:
        """Reject non-finite benchmark measurements."""
        if value is not None and not value.is_finite():
            raise ValueError("benchmark measurements must be finite")
        return value


class QualityEvidence(BaseModel):
    """Normalized quality evidence from benchmarks or imported sources."""

    model_config = ConfigDict(frozen=True)

    evidence_id: str = Field(default_factory=lambda: str(uuid4()), min_length=1)
    model_id: str = Field(min_length=1)
    task: Optional[str] = None
    score: Decimal
    evaluator: str
    source: str
    sample_count: int = Field(default=1, ge=1)
    observed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def _finite_score(cls, value: Decimal) -> Decimal:
        """Reject a non-finite quality score."""
        if not value.is_finite():
            raise ValueError("quality score must be finite")
        return value

    @field_validator("observed_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        """Normalize the observation timestamp to UTC."""
        return _utc(value)


class PayloadPolicy(StrEnum):
    """Policy for prompt and response persistence."""

    NONE = "none"
    HASH_ONLY = "hash_only"
    FULL = "full"
