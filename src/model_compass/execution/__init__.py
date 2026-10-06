"""Execution backends and normalized completion results."""

from model_compass.execution.backend import (
    MAX_RETRIES_LIMIT,
    ExecutionBackend,
    LiteLLMBackend,
)
from model_compass.execution.errors import (
    ExecutionAuthenticationError,
    ExecutionBadRequestError,
    ExecutionConnectionError,
    ExecutionContextError,
    ExecutionError,
    ExecutionProviderError,
    ExecutionRateLimitError,
    ExecutionTimeoutError,
    MalformedResponseError,
    PartialOutputError,
    classify_exception,
)
from model_compass.execution.models import (
    CompletionRequest,
    CostReconciliation,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    UsageRecord,
    failed_observation,
    reconcile_costs,
)
from model_compass.execution.sinks import NullObservationSink, ObservationSink

__all__ = [
    "MAX_RETRIES_LIMIT",
    "CompletionRequest",
    "CostReconciliation",
    "ExecutionAuthenticationError",
    "ExecutionBackend",
    "ExecutionBadRequestError",
    "ExecutionConnectionError",
    "ExecutionContextError",
    "ExecutionError",
    "ExecutionProviderError",
    "ExecutionRateLimitError",
    "ExecutionRequest",
    "ExecutionResult",
    "ExecutionStatus",
    "ExecutionTimeoutError",
    "LiteLLMBackend",
    "MalformedResponseError",
    "NullObservationSink",
    "ObservationSink",
    "PartialOutputError",
    "UsageRecord",
    "classify_exception",
    "failed_observation",
    "reconcile_costs",
]
