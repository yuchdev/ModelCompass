"""LiteLLM-backed model execution with privacy-conscious usage capture."""

from __future__ import annotations

import importlib
import json
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol, cast

from pydantic import BaseModel, ConfigDict, Field

from model_compass.exceptions import DependencyError, ModelCompassError
from model_compass.metrics import Observation

CompletionCall = Callable[..., Awaitable[Any]]

_logger = logging.getLogger(__name__)


class ExecutionError(ModelCompassError):
    """Raised when a model completion fails or returns an invalid response."""

    def __init__(self, message: str, *, latency_ms: Optional[int] = None):
        """Store the sanitized failure message and the latency observed so far."""
        super().__init__(message)
        self.latency_ms = latency_ms


class CompletionRequest(BaseModel):
    """Execution input; message contents are passed to the provider, not persisted."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    task: str
    messages: list[dict[str, Any]]
    parameters: dict[str, Any] = Field(default_factory=dict)


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


class ExecutionBackend(Protocol):
    """Provider-independent completion contract."""

    async def complete(self, request: CompletionRequest) -> ExecutionResult:
        """Run one completion request and return its normalized result."""
        ...


class LiteLLMBackend:
    """Normalize LiteLLM completion output and usage fields."""

    def __init__(
        self,
        *,
        completion_call: Optional[CompletionCall] = None,
        api_key: Optional[str] = None,
    ):
        """Store the injected completion callable (or defer to LiteLLM) and API key."""
        self._completion_call = completion_call
        self._api_key = api_key

    async def complete(self, request: CompletionRequest) -> ExecutionResult:
        """Call the completion backend and normalize its response or failure."""
        completion_call = self._completion_call or _get_completion_call()
        known_failures = _completion_failure_types()
        start = time.perf_counter_ns()
        try:
            parameters = dict(request.parameters)
            if self._api_key is not None:
                parameters["api_key"] = self._api_key
            response = await completion_call(
                model=request.model_id,
                messages=request.messages,
                **parameters,
            )
        except known_failures as exc:
            elapsed = (time.perf_counter_ns() - start) // 1_000_000
            raise ExecutionError(
                f"LiteLLM completion failed ({type(exc).__name__})",
                latency_ms=elapsed,
            ) from exc
        latency_ms = (time.perf_counter_ns() - start) // 1_000_000
        choices = _get(response, "choices", [])
        if not choices:
            raise ExecutionError("LiteLLM completion returned no choices", latency_ms=latency_ms)
        message = _get(choices[0], "message", None)
        content = _get(message, "content", None)
        if isinstance(content, str):
            output_text = content
        elif content is None:
            output_text = ""
        else:
            output_text = json.dumps(content, sort_keys=True)

        usage = _get(response, "usage", None)
        hidden = _get(response, "_hidden_params", {})
        return ExecutionResult(
            model_id=request.model_id,
            task=request.task,
            output_text=output_text,
            latency_ms=latency_ms,
            input_tokens=_as_int(_get(usage, "prompt_tokens", None)),
            output_tokens=_as_int(_get(usage, "completion_tokens", None)),
            actual_cost_usd=_as_decimal(_get(hidden, "response_cost", None)),
        )


def _get(value: Any, key: str, default: Any) -> Any:
    """Read `key` from a dict or object `value`, falling back to `default`."""
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _as_int(value: Any) -> Optional[int]:
    """Coerce a usage field to a non-negative int, or None if it isn't one."""
    if isinstance(value, int) and value >= 0:
        return value
    return None


def _as_decimal(value: Any) -> Optional[Decimal]:
    """Coerce a provider cost field to a finite, non-negative Decimal, or None."""
    if value is None:
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        _logger.debug("Ignoring unparseable response_cost value: %r", value)
        return None
    return result if result.is_finite() and result >= 0 else None


def _completion_failure_types() -> tuple[type[Exception], ...]:
    """Return the known exception types a real completion call can raise."""
    litellm_exceptions = importlib.import_module("litellm.exceptions")
    return (*litellm_exceptions.LITELLM_EXCEPTION_TYPES, TimeoutError, ConnectionError, OSError)


def _get_completion_call() -> CompletionCall:
    """Resolve LiteLLM's acompletion, raising DependencyError if unavailable."""
    try:
        litellm_module = importlib.import_module("litellm")
    except ImportError as exc:
        raise DependencyError("LiteLLM is required for model execution") from exc
    return cast(CompletionCall, litellm_module.acompletion)
