"""Execution backends and normalized completion results."""

from model_compass.execution.backend import (
    CompletionRequest,
    ExecutionBackend,
    ExecutionError,
    ExecutionResult,
    LiteLLMBackend,
)

__all__ = [
    "CompletionRequest",
    "ExecutionBackend",
    "ExecutionError",
    "ExecutionResult",
    "LiteLLMBackend",
]
