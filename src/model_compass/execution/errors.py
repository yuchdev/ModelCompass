"""Execution failure taxonomy; messages never carry provider text or credentials."""

from __future__ import annotations

from typing import Optional

from model_compass.exceptions import ModelCompassError


class ExecutionError(ModelCompassError):
    """Raised when a model completion fails or returns an invalid response."""

    category = "execution_error"

    def __init__(
        self,
        message: str,
        *,
        latency_ms: Optional[int] = None,
        time_to_first_token_ms: Optional[int] = None,
    ):
        """Store the sanitized failure message and the timings observed so far."""
        super().__init__(message)
        self.latency_ms = latency_ms
        self.time_to_first_token_ms = time_to_first_token_ms
        self.observation_id: Optional[str] = None


class ExecutionTimeoutError(ExecutionError):
    """The provider did not answer within the configured timeout."""

    category = "timeout"


class ExecutionAuthenticationError(ExecutionError):
    """The provider rejected the credentials or the account lacks permission."""

    category = "authentication"


class ExecutionRateLimitError(ExecutionError):
    """The provider throttled the request."""

    category = "rate_limit"


class ExecutionContextError(ExecutionError):
    """The request exceeded the model's context window or violated content limits."""

    category = "context_length"


class ExecutionBadRequestError(ExecutionError):
    """The provider rejected the request as invalid."""

    category = "bad_request"


class ExecutionConnectionError(ExecutionError):
    """The provider could not be reached."""

    category = "connection"


class ExecutionProviderError(ExecutionError):
    """Any other provider-side or LiteLLM failure."""

    category = "provider_error"


class MalformedResponseError(ExecutionError):
    """The provider answered, but the response could not be normalized."""

    category = "malformed_response"


class PartialOutputError(ExecutionError):
    """A stream failed after some output was received; the output is incomplete."""

    category = "partial_output"

    def __init__(
        self,
        message: str,
        *,
        partial_output: str = "",
        latency_ms: Optional[int] = None,
        time_to_first_token_ms: Optional[int] = None,
    ):
        """Keep the partial text separate so callers cannot mistake it for a result."""
        super().__init__(message, latency_ms=latency_ms, time_to_first_token_ms=time_to_first_token_ms)
        self.partial_output = partial_output


_BY_NAME: tuple[tuple[tuple[str, ...], type[ExecutionError]], ...] = (
    (("ContextWindowExceededError", "ContentPolicyViolationError"), ExecutionContextError),
    (("AuthenticationError", "PermissionDeniedError"), ExecutionAuthenticationError),
    (("RateLimitError",), ExecutionRateLimitError),
    (("Timeout", "TimeoutError", "APITimeoutError", "TimeoutException"), ExecutionTimeoutError),
    (("APIConnectionError", "ConnectionError", "NetworkError"), ExecutionConnectionError),
    (
        ("BadRequestError", "UnprocessableEntityError", "NotFoundError", "UnsupportedParamsError"),
        ExecutionBadRequestError,
    ),
)


def classify_exception(exc: BaseException, *, latency_ms: Optional[int] = None) -> ExecutionError:
    """Map a LiteLLM, provider, or built-in exception to a sanitized project exception.

    Classification walks the exception's MRO by class name so no LiteLLM import is needed
    and a subclass of a known provider error keeps its category. Only the exception type
    name is reported; its message is dropped because providers sometimes echo credentials.
    """
    names = {cls.__name__ for cls in type(exc).__mro__}
    for candidates, error_type in _BY_NAME:
        if names.intersection(candidates):
            return error_type(f"LiteLLM completion failed ({type(exc).__name__})", latency_ms=latency_ms)
    return ExecutionProviderError(f"LiteLLM completion failed ({type(exc).__name__})", latency_ms=latency_ms)
