"""LiteLLM-backed model execution with privacy-conscious usage capture.

This and ``catalogs/litellm.py`` are the only places LiteLLM is imported; the rest of the
package depends on :class:`ExecutionBackend` and the DTOs in :mod:`.models`.
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import logging
import time
from collections.abc import Awaitable, Callable
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol, cast

from model_compass.exceptions import ConfigurationError, DependencyError
from model_compass.execution.errors import (
    ExecutionError,
    MalformedResponseError,
    PartialOutputError,
    classify_exception,
)
from model_compass.execution.models import (
    COST_SOURCE_ACTUAL,
    COST_SOURCE_COMPUTED,
    CompletionRequest,
    ExecutionRequest,
    ExecutionResult,
    UsageRecord,
    status_from_finish_reason,
)

CompletionCall = Callable[..., Awaitable[Any]]
CostCall = Callable[[str, int, int], Optional[Decimal]]

MAX_RETRIES_LIMIT = 5

_logger = logging.getLogger(__name__)

__all__ = [
    "MAX_RETRIES_LIMIT",
    "CompletionCall",
    "CompletionRequest",
    "CostCall",
    "ExecutionBackend",
    "ExecutionError",
    "ExecutionRequest",
    "ExecutionResult",
    "LiteLLMBackend",
]


class ExecutionBackend(Protocol):
    """Provider-independent execution contract."""

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Run one request and return its normalized result, raising ExecutionError on failure."""
        ...


class LiteLLMBackend:
    """Run requests through LiteLLM and normalize output, usage, cost, and failures.

    Retries are delegated to LiteLLM's ``num_retries`` and bounded by ``max_retries``
    (default 0, at most :data:`MAX_RETRIES_LIMIT`). Retries re-send the same model; each
    retry can be billed by the provider, and the configured count is reported in
    ``result.metadata["max_retries"]`` because LiteLLM does not report how many occurred.
    """

    def __init__(
        self,
        *,
        completion_call: Optional[CompletionCall] = None,
        api_key: Optional[str] = None,
        cost_call: Optional[CostCall] = None,
        max_retries: int = 0,
        model_resolver: Optional[Callable[[str], str]] = None,
        on_text_delta: Optional[Callable[[str], None]] = None,
    ):
        """Store injected collaborators, the API key, and the bounded retry policy."""
        if not 0 <= max_retries <= MAX_RETRIES_LIMIT:
            raise ConfigurationError(f"max_retries must be between 0 and {MAX_RETRIES_LIMIT}")
        self._completion_call = completion_call
        self._api_key = api_key
        self._cost_call = cost_call
        self._max_retries = max_retries
        self._model_resolver = model_resolver
        self._on_text_delta = on_text_delta

    def __repr__(self) -> str:
        """Describe the backend without revealing the API key."""
        return f"LiteLLMBackend(max_retries={self._max_retries}, api_key={'set' if self._api_key else 'unset'})"

    async def complete(self, request: ExecutionRequest) -> ExecutionResult:
        """Alias for :meth:`execute`, kept for callers written against the earlier API."""
        return await self.execute(request)

    async def execute(self, request: ExecutionRequest) -> ExecutionResult:
        """Call LiteLLM and normalize its response or failure."""
        completion_call = self._completion_call or _get_completion_call()
        model = self._model_resolver(request.model_id) if self._model_resolver else request.model_id
        kwargs = self._build_kwargs(request, model)
        start = time.perf_counter_ns()
        if request.stream:
            return await self._execute_stream(completion_call, request, model, kwargs, start)
        try:
            response = await completion_call(**kwargs)
        except _failure_types() as exc:
            raise classify_exception(exc, latency_ms=_elapsed_ms(start)) from exc
        latency_ms = _elapsed_ms(start)
        try:
            return self._normalize(request, model, response, latency_ms=latency_ms)
        except ExecutionError as exc:
            exc.latency_ms = latency_ms
            raise
        except _NORMALIZATION_ERRORS as exc:
            raise MalformedResponseError(
                f"LiteLLM completion returned a malformed response ({type(exc).__name__})",
                latency_ms=latency_ms,
            ) from exc

    def _build_kwargs(self, request: ExecutionRequest, model: str) -> dict[str, Any]:
        """Assemble LiteLLM call arguments; credentials and retries come only from backend config."""
        kwargs: dict[str, Any] = dict(request.parameters)
        kwargs["model"] = model
        kwargs["messages"] = request.messages
        if request.tools is not None:
            kwargs["tools"] = request.tools
        if request.response_format is not None:
            kwargs["response_format"] = request.response_format
        if request.provider_routing:
            kwargs["extra_body"] = {**dict(kwargs.get("extra_body") or {}), "provider": request.provider_routing}
        if request.stream:
            kwargs["stream"] = True
            kwargs.setdefault("stream_options", {"include_usage": True})
        if self._max_retries:
            kwargs["num_retries"] = self._max_retries
        else:
            kwargs.pop("num_retries", None)
        if self._api_key is not None:
            kwargs["api_key"] = self._api_key
        return kwargs

    async def _execute_stream(
        self,
        completion_call: CompletionCall,
        request: ExecutionRequest,
        model: str,
        kwargs: dict[str, Any],
        start: int,
    ) -> ExecutionResult:
        """Consume a real provider stream, measuring TTFT, and finalize only when it ends."""
        text_parts: list[str] = []
        tool_fragments: dict[int, dict[str, Any]] = {}
        finish_reason: Optional[str] = None
        usage: Any = None
        hidden: Any = None
        ttft_ms: Optional[int] = None
        try:
            stream = await completion_call(**kwargs)
            async for chunk in stream:
                choices = _get(chunk, "choices", None) or []
                delta = _get(choices[0], "delta", None) if choices else None
                content = _get(delta, "content", None)
                fragments = _get(delta, "tool_calls", None) or []
                if ttft_ms is None and ((isinstance(content, str) and content) or fragments):
                    ttft_ms = _elapsed_ms(start)
                if isinstance(content, str) and content:
                    text_parts.append(content)
                    if self._on_text_delta is not None:
                        self._on_text_delta(content)
                for fragment in fragments:
                    _merge_tool_fragment(tool_fragments, fragment)
                if choices and _get(choices[0], "finish_reason", None):
                    finish_reason = str(_get(choices[0], "finish_reason", None))
                chunk_usage = _get(chunk, "usage", None)
                if chunk_usage is not None:
                    usage = chunk_usage
                chunk_hidden = _get(chunk, "_hidden_params", None)
                if chunk_hidden:
                    hidden = chunk_hidden
        except _failure_types() as exc:
            latency_ms = _elapsed_ms(start)
            if text_parts or tool_fragments:
                raise PartialOutputError(
                    f"LiteLLM stream failed after partial output ({type(exc).__name__})",
                    partial_output="".join(text_parts),
                    latency_ms=latency_ms,
                    time_to_first_token_ms=ttft_ms,
                ) from exc
            error = classify_exception(exc, latency_ms=latency_ms)
            error.time_to_first_token_ms = ttft_ms
            raise error from exc
        latency_ms = _elapsed_ms(start)
        return self._build_result(
            request,
            model,
            output_text="".join(text_parts),
            tool_calls=[tool_fragments[index] for index in sorted(tool_fragments)],
            finish_reason=finish_reason,
            usage=usage,
            hidden=hidden,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            streamed=True,
        )

    def _normalize(self, request: ExecutionRequest, model: str, response: Any, *, latency_ms: int) -> ExecutionResult:
        """Normalize a non-streaming LiteLLM response."""
        choices = _get(response, "choices", [])
        if not choices:
            raise MalformedResponseError("LiteLLM completion returned no choices")
        message = _get(choices[0], "message", None)
        content = _get(message, "content", None)
        if isinstance(content, str):
            output_text = content
        elif content is None:
            output_text = ""
        else:
            output_text = json.dumps(content, sort_keys=True)
        raw_tool_calls = _get(message, "tool_calls", None) or []
        finish = _get(choices[0], "finish_reason", None)
        return self._build_result(
            request,
            model,
            output_text=output_text,
            tool_calls=[_plain(call) for call in raw_tool_calls],
            finish_reason=str(finish) if finish is not None else None,
            usage=_get(response, "usage", None),
            hidden=_get(response, "_hidden_params", {}),
            latency_ms=latency_ms,
            ttft_ms=None,
            streamed=False,
        )

    def _build_result(
        self,
        request: ExecutionRequest,
        model: str,
        *,
        output_text: str,
        tool_calls: list[dict[str, Any]],
        finish_reason: Optional[str],
        usage: Any,
        hidden: Any,
        latency_ms: int,
        ttft_ms: Optional[int],
        streamed: bool,
    ) -> ExecutionResult:
        """Combine normalized pieces into a result, separating actual from computed cost."""
        usage_record = _normalize_usage(usage)
        actual = _as_decimal(_get(hidden, "response_cost", None))
        computed: Optional[Decimal] = None
        if actual is None and usage_record is not None:
            computed = self._compute_cost(model, usage_record)
        cost_source = (
            COST_SOURCE_ACTUAL if actual is not None else COST_SOURCE_COMPUTED if computed is not None else None
        )
        return ExecutionResult(
            model_id=request.model_id,
            task=request.task,
            output_text=output_text,
            latency_ms=latency_ms,
            input_tokens=usage_record.input_tokens if usage_record else None,
            output_tokens=usage_record.output_tokens if usage_record else None,
            actual_cost_usd=actual,
            usage=usage_record,
            computed_cost_usd=computed,
            cost_source=cost_source,
            finish_reason=finish_reason,
            status=status_from_finish_reason(finish_reason),
            time_to_first_token_ms=ttft_ms,
            streamed=streamed,
            tool_calls=tool_calls,
            metadata={"max_retries": self._max_retries},
        )

    def _compute_cost(self, model: str, usage: UsageRecord) -> Optional[Decimal]:
        """Price the reported tokens with the cost callable; None when it cannot."""
        if usage.input_tokens is None or usage.output_tokens is None:
            return None
        try:
            cost_call = self._cost_call or _litellm_cost
            return cost_call(model, usage.input_tokens, usage.output_tokens)
        except _cost_failure_types():
            _logger.debug("Could not compute a cost for %r", model)
            return None


_NORMALIZATION_ERRORS = (KeyError, TypeError, ValueError, AttributeError, IndexError)


def _failure_types() -> tuple[type[BaseException], ...]:
    """Return the exception types a completion call can raise that map to ExecutionError."""
    builtin: tuple[type[BaseException], ...] = (TimeoutError, ConnectionError, OSError, RuntimeError, ValueError)
    if importlib.util.find_spec("litellm") is None:
        return builtin
    litellm_exceptions = importlib.import_module("litellm.exceptions")
    return (*litellm_exceptions.LITELLM_EXCEPTION_TYPES, *builtin)


def _cost_failure_types() -> tuple[type[BaseException], ...]:
    """Return the exception types that mean a cost could not be computed."""
    return (*_failure_types(), KeyError, TypeError, ArithmeticError, ImportError)


def _elapsed_ms(start_ns: int) -> int:
    """Milliseconds elapsed on the monotonic clock since `start_ns`."""
    return (time.perf_counter_ns() - start_ns) // 1_000_000


def _get(value: Any, key: str, default: Any) -> Any:
    """Read `key` from a dict or object `value`, falling back to `default`."""
    if isinstance(value, dict):
        return value.get(key, default)
    return getattr(value, key, default)


def _plain(value: Any) -> Any:
    """Convert dict/pydantic-like provider objects into plain JSON-compatible data."""
    if isinstance(value, dict):
        return {str(key): _plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain(item) for item in value]
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    dumper = getattr(value, "model_dump", None)
    if callable(dumper):
        return _plain(dumper())
    return str(value)


def _merge_tool_fragment(calls: dict[int, dict[str, Any]], fragment: Any):
    """Accumulate one streamed tool-call delta into its call, keyed by index."""
    index = _get(fragment, "index", 0)
    call = calls.setdefault(
        index if isinstance(index, int) else 0,
        {"id": None, "type": "function", "function": {"name": "", "arguments": ""}},
    )
    identifier = _get(fragment, "id", None)
    if identifier:
        call["id"] = identifier
    function = _get(fragment, "function", None)
    name = _get(function, "name", None)
    if name:
        call["function"]["name"] += name
    arguments = _get(function, "arguments", None)
    if arguments:
        call["function"]["arguments"] += arguments


def _as_int(value: Any) -> Optional[int]:
    """Coerce a usage field to a non-negative int, or None if it isn't one."""
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
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


_BASIC_USAGE_KEYS = frozenset({"prompt_tokens", "completion_tokens", "total_tokens"})


def _normalize_usage(usage: Any) -> Optional[UsageRecord]:
    """Normalize LiteLLM/OpenAI-style usage; unavailable fields stay None.

    Fields that would violate the record's invariants (a total below its parts) are
    dropped and the reason is recorded in ``provider_specific``, never raised, so
    unusual provider accounting does not fail an otherwise good completion.
    """
    if usage is None:
        return None
    prompt_details = _get(usage, "prompt_tokens_details", None)
    completion_details = _get(usage, "completion_tokens_details", None)
    input_tokens = _as_int(_get(usage, "prompt_tokens", None))
    output_tokens = _as_int(_get(usage, "completion_tokens", None))
    total_tokens = _as_int(_get(usage, "total_tokens", None))
    extras = (
        {key: value for key, value in _plain(usage).items() if key not in _BASIC_USAGE_KEYS and value is not None}
        if isinstance(_plain(usage), dict)
        else {}
    )
    if total_tokens is not None and any(
        part is not None and part > total_tokens for part in (input_tokens, output_tokens)
    ):
        extras["normalization_warning"] = f"dropped inconsistent total_tokens={total_tokens}"
        total_tokens = None
    cached_read = _as_int(_get(prompt_details, "cached_tokens", None))
    if cached_read is None:
        cached_read = _as_int(_get(usage, "cache_read_input_tokens", None))
    cached_write = _as_int(_get(usage, "cache_creation_input_tokens", None))
    return UsageRecord(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=total_tokens,
        cached_read_tokens=cached_read,
        cached_write_tokens=cached_write,
        reasoning_tokens=_as_int(_get(completion_details, "reasoning_tokens", None)),
        provider_specific=extras,
    )


def _litellm_cost(model: str, input_tokens: int, output_tokens: int) -> Optional[Decimal]:
    """Price tokens with LiteLLM's bundled price table; raises for unknown models."""
    litellm_module = importlib.import_module("litellm")
    prompt_cost, completion_cost = litellm_module.cost_per_token(
        model=model, prompt_tokens=input_tokens, completion_tokens=output_tokens
    )
    return _as_decimal(Decimal(str(prompt_cost)) + Decimal(str(completion_cost)))


def _get_completion_call() -> CompletionCall:
    """Resolve LiteLLM's acompletion, raising DependencyError if unavailable."""
    try:
        litellm_module = importlib.import_module("litellm")
    except ImportError as exc:
        raise DependencyError("LiteLLM is required for model execution") from exc
    return cast(CompletionCall, litellm_module.acompletion)
