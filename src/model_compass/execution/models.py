"""Backend-neutral execution DTOs: requests, usage, results, and cost reconciliation."""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model_compass.domain import Observation as StoredObservation
from model_compass.execution.errors import ExecutionError
from model_compass.metrics import Observation

COST_SOURCE_ACTUAL = "provider_reported"
COST_SOURCE_COMPUTED = "computed"

_SECRET_KEYS = frozenset(
    {
        "api_key",
        "authorization",
        "proxy_authorization",
        "x_api_key",
        "secret",
        "client_secret",
        "password",
        "token",
        "access_token",
        "aws_secret_access_key",
        "aws_session_token",
    }
)


_FALLBACK_KEYS = frozenset({"fallbacks", "context_window_fallback_dict", "content_policy_fallbacks", "models", "route"})


def _contains_key(value: Any, keys: frozenset[str], *, suffix: str = "\0") -> Optional[str]:
    """Return the first key (normalized to lower snake case) in `keys` found in nested data."""
    if isinstance(value, dict):
        for key, nested in value.items():
            normalized = str(key).lower().replace("-", "_")
            if normalized in keys or normalized.endswith(suffix):
                return str(key)
            found = _contains_key(nested, keys, suffix=suffix)
            if found is not None:
                return found
    elif isinstance(value, (list, tuple)):
        for item in value:
            found = _contains_key(item, keys, suffix=suffix)
            if found is not None:
                return found
    return None


def _contains_secret_key(value: Any) -> Optional[str]:
    """Return the first credential-looking key found in nested data, if any."""
    return _contains_key(value, _SECRET_KEYS, suffix="_api_key")


class ExecutionRequest(BaseModel):
    """Serializable execution input.

    Credentials are deliberately not representable here: configure them on the backend.
    Message contents go to the provider but are not persisted by observations.
    """

    model_config = ConfigDict(frozen=True)

    model_id: str = Field(min_length=1)
    task: str
    messages: list[dict[str, Any]]
    tools: Optional[list[dict[str, Any]]] = None
    response_format: Optional[dict[str, Any]] = None
    parameters: dict[str, Any] = Field(default_factory=dict)
    stream: bool = False
    provider_routing: Optional[dict[str, Any]] = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("parameters", "provider_routing")
    @classmethod
    def _no_hidden_fallbacks(cls, value: Any) -> Any:
        """Reject keys that would make the provider layer switch models behind the caller's back."""
        found = _contains_key(value, _FALLBACK_KEYS)
        if found is not None:
            raise ValueError(f"{found!r} would enable implicit multi-model fallback, which is not supported")
        return value

    @field_validator("parameters", "provider_routing", "tools", "response_format")
    @classmethod
    def _no_credentials(cls, value: Any) -> Any:
        """Reject credential-looking keys so secrets never ride in serializable requests."""
        found = _contains_secret_key(value)
        if found is not None:
            raise ValueError(f"credential-like key {found!r} is not allowed in a request; configure it on the backend")
        return value

    @classmethod
    def from_prompt(cls, model_id: str, task: str, prompt: str, **options: Any) -> ExecutionRequest:
        """Build a request from a single user prompt."""
        return cls(model_id=model_id, task=task, messages=[{"role": "user", "content": prompt}], **options)


CompletionRequest = ExecutionRequest


class UsageRecord(BaseModel):
    """Normalized token usage; ``None`` means the provider did not report the field."""

    model_config = ConfigDict(frozen=True)

    input_tokens: Optional[int] = Field(default=None, ge=0)
    output_tokens: Optional[int] = Field(default=None, ge=0)
    total_tokens: Optional[int] = Field(default=None, ge=0)
    cached_read_tokens: Optional[int] = Field(default=None, ge=0)
    cached_write_tokens: Optional[int] = Field(default=None, ge=0)
    reasoning_tokens: Optional[int] = Field(default=None, ge=0)
    provider_specific: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _total_covers_parts(self) -> UsageRecord:
        """Reject a total smaller than the input or output it is supposed to include.

        Cache and reasoning counts are not cross-checked: providers disagree on whether they
        are included in or additional to input and output.
        """
        if self.total_tokens is not None:
            for part in (self.input_tokens, self.output_tokens):
                if part is not None and part > self.total_tokens:
                    raise ValueError("total_tokens cannot be smaller than input_tokens or output_tokens")
        return self


class ExecutionStatus(StrEnum):
    """How a completion ended, derived from the provider's finish reason."""

    COMPLETED = "completed"
    TRUNCATED = "truncated"
    CONTENT_FILTERED = "content_filtered"
    UNKNOWN = "unknown"


def status_from_finish_reason(finish_reason: Optional[str]) -> ExecutionStatus:
    """Classify a provider finish reason."""
    if finish_reason in {"stop", "tool_calls", "function_call", "end_turn", "tool_use", "stop_sequence"}:
        return ExecutionStatus.COMPLETED
    if finish_reason in {"length", "max_tokens"}:
        return ExecutionStatus.TRUNCATED
    if finish_reason == "content_filter":
        return ExecutionStatus.CONTENT_FILTERED
    return ExecutionStatus.UNKNOWN


class CostReconciliation(BaseModel):
    """Estimated-versus-actual cost; incomplete when either side is unavailable."""

    model_config = ConfigDict(frozen=True)

    estimated_before: Optional[Decimal] = None
    actual_after: Optional[Decimal] = None
    absolute_error: Optional[Decimal] = None
    relative_error: Optional[Decimal] = None
    actual_source: Optional[str] = None

    @property
    def is_complete(self) -> bool:
        """Whether both costs were available, so the error figures are meaningful."""
        return self.estimated_before is not None and self.actual_after is not None

    def to_metadata(self) -> dict[str, Optional[str]]:
        """Return a JSON-safe form with Decimals as strings."""
        return {
            "estimated_before": _text(self.estimated_before),
            "actual_after": _text(self.actual_after),
            "absolute_error": _text(self.absolute_error),
            "relative_error": _text(self.relative_error),
            "actual_source": self.actual_source,
            "complete": str(self.is_complete).lower(),
        }


def reconcile_costs(
    estimated_before: Optional[Decimal],
    actual_after: Optional[Decimal],
    *,
    actual_source: Optional[str] = None,
) -> CostReconciliation:
    """Compare a pre-request estimate with the actual cost.

    Errors are ``None`` (never zero) when either side is missing. ``relative_error`` is
    relative to the actual cost and is ``None`` when the actual cost is zero but the
    estimate is not, because the ratio is undefined.
    """
    absolute_error: Optional[Decimal] = None
    relative_error: Optional[Decimal] = None
    if estimated_before is not None and actual_after is not None:
        absolute_error = abs(actual_after - estimated_before)
        if actual_after > 0:
            relative_error = absolute_error / actual_after
        elif absolute_error == 0:
            relative_error = Decimal(0)
    return CostReconciliation(
        estimated_before=estimated_before,
        actual_after=actual_after,
        absolute_error=absolute_error,
        relative_error=relative_error,
        actual_source=actual_source if actual_after is not None else None,
    )


class ExecutionResult(BaseModel):
    """Completion output and normalized usage measurements."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    output_text: str
    latency_ms: int
    input_tokens: Optional[int] = None
    output_tokens: Optional[int] = None
    actual_cost_usd: Optional[Decimal] = None
    usage: Optional[UsageRecord] = None
    computed_cost_usd: Optional[Decimal] = None
    cost_source: Optional[str] = None
    finish_reason: Optional[str] = None
    status: ExecutionStatus = ExecutionStatus.UNKNOWN
    time_to_first_token_ms: Optional[int] = None
    streamed: bool = False
    tool_calls: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    def to_observation(self) -> Observation:
        """Convert usage into a prompt-free local observation."""
        return Observation(
            model_id=self.model_id,
            task=self.task,
            succeeded=True,
            latency_ms=self.latency_ms,
            actual_cost_usd=self.actual_cost_usd,
            input_tokens=self.input_tokens,
            output_tokens=self.output_tokens,
        )

    def reconcile(self, estimated_before: Optional[Decimal]) -> CostReconciliation:
        """Reconcile a pre-request estimate with this result's actual cost."""
        return reconcile_costs(
            estimated_before,
            self.actual_cost_usd,
            actual_source=self.cost_source if self.actual_cost_usd is not None else None,
        )

    def to_stored_observation(
        self,
        *,
        estimated_before: Optional[Decimal] = None,
        reconciliation: Optional[CostReconciliation] = None,
    ) -> StoredObservation:
        """Build the persistent observation, without prompt or response text.

        ``estimated_cost`` holds the pre-request estimate when given, else the post-hoc
        computed cost. The reconciliation, retry configuration, and any computed cost are
        kept in metadata so actual and estimated figures stay distinguishable.
        """
        usage = self.usage or UsageRecord(input_tokens=self.input_tokens, output_tokens=self.output_tokens)
        metadata: dict[str, Any] = {"streamed": self.streamed, "status": self.status.value}
        metadata.update({key: value for key, value in self.metadata.items() if key in _PERSISTED_METADATA})
        if self.computed_cost_usd is not None:
            metadata["computed_cost_usd"] = str(self.computed_cost_usd)
        if reconciliation is None and estimated_before is not None:
            reconciliation = self.reconcile(estimated_before)
        if reconciliation is not None:
            metadata["cost_reconciliation"] = reconciliation.to_metadata()
        return StoredObservation(
            model_id=self.model_id,
            task=self.task,
            success=True,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cached_read_tokens=usage.cached_read_tokens,
            cached_write_tokens=usage.cached_write_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            estimated_cost=estimated_before if estimated_before is not None else self.computed_cost_usd,
            actual_cost=self.actual_cost_usd,
            cost_source=self.cost_source,
            latency_ms=Decimal(self.latency_ms),
            time_to_first_token_ms=(
                Decimal(self.time_to_first_token_ms) if self.time_to_first_token_ms is not None else None
            ),
            finish_reason=self.finish_reason,
            metadata=metadata,
        )


_PERSISTED_METADATA = frozenset({"max_retries", "retries_configured"})


def failed_observation(
    request: ExecutionRequest,
    error: ExecutionError,
    *,
    estimated_before: Optional[Decimal] = None,
) -> StoredObservation:
    """Build the persistent observation for a failed execution; no error text is stored."""
    metadata: dict[str, Any] = {"streamed": request.stream}
    partial = getattr(error, "partial_output", None)
    if partial is not None:
        metadata["partial_output"] = True
    return StoredObservation(
        model_id=request.model_id,
        task=request.task,
        success=False,
        failure_category=error.category,
        estimated_cost=estimated_before,
        latency_ms=Decimal(error.latency_ms) if error.latency_ms is not None else None,
        time_to_first_token_ms=(
            Decimal(error.time_to_first_token_ms) if error.time_to_first_token_ms is not None else None
        ),
        metadata=metadata,
    )


def _text(value: Optional[Decimal]) -> Optional[str]:
    """Render an optional Decimal as a string."""
    return str(value) if value is not None else None
