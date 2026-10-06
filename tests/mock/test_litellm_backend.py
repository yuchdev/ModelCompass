from __future__ import annotations

import json
import traceback
from collections.abc import AsyncIterator
from decimal import Decimal
from types import SimpleNamespace
from typing import Any, Optional

import litellm
import pytest
from pydantic import ValidationError

from model_compass.exceptions import ConfigurationError, DependencyError
from model_compass.execution import (
    ExecutionAuthenticationError,
    ExecutionContextError,
    ExecutionProviderError,
    ExecutionRateLimitError,
    ExecutionRequest,
    ExecutionStatus,
    ExecutionTimeoutError,
    LiteLLMBackend,
    MalformedResponseError,
    PartialOutputError,
)
from model_compass.execution import backend as backend_module

SECRET = "sk-test-very-secret-key"


def _request(**overrides: Any) -> ExecutionRequest:
    """Build a small request for the mocked backend."""
    fields: dict[str, Any] = {"model_id": "prov/model", "task": "qa", "messages": [{"role": "user", "content": "hi"}]}
    fields.update(overrides)
    return ExecutionRequest.model_validate(fields)


class Recorder:
    """Awaitable completion double that records kwargs and returns or raises a scripted outcome."""

    def __init__(self, outcome: Any):
        """Store the scripted outcome (a response, or an exception to raise)."""
        self.outcome = outcome
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        """Record the call and return or raise the scripted outcome."""
        self.calls.append(kwargs)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def _response(**overrides: Any) -> dict[str, Any]:
    """Return a well-formed non-streaming completion payload."""
    payload: dict[str, Any] = {
        "choices": [{"message": {"content": "hello"}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 3, "total_tokens": 15},
        "_hidden_params": {"response_cost": "0.000042"},
    }
    payload.update(overrides)
    return payload


def _cost(model: str, input_tokens: int, output_tokens: int) -> Decimal:
    """Price tokens at a flat deterministic rate."""
    return Decimal(input_tokens + output_tokens) / Decimal(1000)


@pytest.mark.mock
async def test_normal_response_is_normalized():
    """[Local] normal response: output, finish status, usage, cost, and latency are captured.

    Scenario: A mocked completion returns text, usage, finish_reason, and a response cost.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend._normalize and _build_result.
    """
    recorder = Recorder(_response())
    result = await LiteLLMBackend(completion_call=recorder, cost_call=_cost).execute(_request())

    assert result.output_text == "hello"
    assert result.finish_reason == "stop"
    assert result.status is ExecutionStatus.COMPLETED
    assert result.latency_ms >= 0
    assert result.streamed is False
    assert result.usage is not None
    assert (result.usage.input_tokens, result.usage.output_tokens, result.usage.total_tokens) == (12, 3, 15)
    assert (result.input_tokens, result.output_tokens) == (12, 3)
    assert result.actual_cost_usd == Decimal("0.000042")
    assert result.cost_source == "provider_reported"
    assert result.computed_cost_usd is None
    assert result.metadata["max_retries"] == 0
    assert recorder.calls[0]["model"] == "prov/model"
    assert "num_retries" not in recorder.calls[0]
    assert "api_key" not in recorder.calls[0]


@pytest.mark.mock
async def test_complete_alias_and_model_resolver():
    """[Local] compatibility: complete() aliases execute() and a resolver maps canonical ids to LiteLLM names.

    Scenario: Call complete() with a resolver that rewrites the canonical id.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend.complete and the model_resolver wiring.
    """
    recorder = Recorder(_response())
    backend = LiteLLMBackend(completion_call=recorder, model_resolver=lambda cid: cid.replace(":", "/"))
    result = await backend.complete(_request(model_id="openrouter:vendor/model"))
    assert recorder.calls[0]["model"] == "openrouter/vendor/model"
    assert result.model_id == "openrouter:vendor/model"


@pytest.mark.mock
async def test_usage_partially_missing_stays_none():
    """[Local] partial usage: fields the provider omits stay None rather than becoming zero.

    Scenario: Usage carries only prompt_tokens; another response has no usage at all.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: backend._normalize_usage.
    """
    partial = await LiteLLMBackend(
        completion_call=Recorder(_response(usage={"prompt_tokens": 7}, _hidden_params={})), cost_call=_cost
    ).execute(_request())
    assert partial.usage is not None
    assert partial.usage.input_tokens == 7
    assert partial.usage.output_tokens is None
    assert partial.usage.total_tokens is None
    assert partial.computed_cost_usd is None  # needs both token counts
    assert partial.cost_source is None

    absent = await LiteLLMBackend(completion_call=Recorder(_response(usage=None, _hidden_params={}))).execute(
        _request()
    )
    assert absent.usage is None
    assert absent.input_tokens is None
    assert absent.actual_cost_usd is None
    assert absent.cost_source is None


@pytest.mark.mock
async def test_usage_details_cache_reasoning_and_provider_specific():
    """[Local] usage details: cache and reasoning counts are normalized and extras are preserved.

    Scenario: Usage includes OpenAI-style details, Anthropic-style cache fields, and an inconsistent total.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: backend._normalize_usage.
    """
    usage = {
        "prompt_tokens": 100,
        "completion_tokens": 50,
        "total_tokens": 150,
        "prompt_tokens_details": {"cached_tokens": 40},
        "completion_tokens_details": {"reasoning_tokens": 20},
        "cache_creation_input_tokens": 5,
        "vendor_field": "x",
    }
    result = await LiteLLMBackend(completion_call=Recorder(_response(usage=usage))).execute(_request())
    assert result.usage is not None
    assert result.usage.cached_read_tokens == 40
    assert result.usage.cached_write_tokens == 5
    assert result.usage.reasoning_tokens == 20
    assert result.usage.provider_specific["vendor_field"] == "x"
    assert result.usage.provider_specific["prompt_tokens_details"] == {"cached_tokens": 40}

    anthropic = await LiteLLMBackend(
        completion_call=Recorder(_response(usage={"prompt_tokens": 1, "cache_read_input_tokens": 9}))
    ).execute(_request())
    assert anthropic.usage is not None
    assert anthropic.usage.cached_read_tokens == 9

    inconsistent = await LiteLLMBackend(
        completion_call=Recorder(_response(usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 3}))
    ).execute(_request())
    assert inconsistent.usage is not None
    assert inconsistent.usage.total_tokens is None
    assert "normalization_warning" in inconsistent.usage.provider_specific
    assert inconsistent.input_tokens == 10


@pytest.mark.mock
async def test_object_style_response_and_bool_usage_ignored():
    """[Local] attribute-style responses: SDK objects are read like dicts and bool usage is not a count.

    Scenario: The response is a SimpleNamespace tree, with a boolean prompt_tokens value.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: backend._get, _plain, and _as_int.
    """
    response = SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content="obj", tool_calls=None), finish_reason="length")],
        usage=SimpleNamespace(prompt_tokens=True, completion_tokens=2, total_tokens=2),
        _hidden_params={"response_cost": 0.5},
    )
    result = await LiteLLMBackend(completion_call=Recorder(response)).execute(_request())
    assert result.output_text == "obj"
    assert result.status is ExecutionStatus.TRUNCATED
    assert result.usage is not None
    assert result.usage.input_tokens is None
    assert result.actual_cost_usd == Decimal("0.5")


@pytest.mark.mock
async def test_actual_cost_present_is_actual_not_estimate():
    """[Local] actual cost: a provider-reported cost is recorded as actual and the estimate is not computed.

    Scenario: The response exposes response_cost while a cost callable is also configured.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend._build_result cost branching.
    """
    calls: list[str] = []

    def spy(model: str, input_tokens: int, output_tokens: int) -> Decimal:
        """Record that the estimator ran."""
        calls.append(model)
        return Decimal(1)

    result = await LiteLLMBackend(completion_call=Recorder(_response()), cost_call=spy).execute(_request())
    assert result.actual_cost_usd == Decimal("0.000042")
    assert result.computed_cost_usd is None
    assert calls == []


@pytest.mark.mock
async def test_no_actual_cost_computes_distinct_estimate():
    """[Local] no actual cost: a computed estimate is recorded separately and actual stays None.

    Scenario: The response has usage but no response_cost; a cost callable prices the tokens.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend._compute_cost and result.cost_source.
    """
    result = await LiteLLMBackend(completion_call=Recorder(_response(_hidden_params={})), cost_call=_cost).execute(
        _request()
    )
    assert result.actual_cost_usd is None
    assert result.computed_cost_usd == Decimal("0.015")
    assert result.cost_source == "computed"
    assert result.reconcile(Decimal("0.01")).is_complete is False


@pytest.mark.mock
async def test_cost_callable_failures_leave_cost_unknown():
    """[Local] cost computation failure: a cost callable that raises yields no cost rather than an error.

    Scenario: The cost callable raises for an unmapped model, and returns a bad value.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend._compute_cost exception handling.
    """

    def unmapped(model: str, input_tokens: int, output_tokens: int) -> Decimal:
        """Fail like LiteLLM does for an unknown model."""
        raise litellm.BadRequestError(message="unmapped", model=model, llm_provider="x")

    result = await LiteLLMBackend(completion_call=Recorder(_response(_hidden_params={})), cost_call=unmapped).execute(
        _request()
    )
    assert result.computed_cost_usd is None
    assert result.cost_source is None


@pytest.mark.mock
async def test_default_cost_call_uses_litellm_price_table():
    """[Local] default pricing: without a cost callable LiteLLM's bundled prices compute the estimate.

    Scenario: No cost_call is injected; a model known to LiteLLM, then an unknown one, are used.
    Boundaries: Real LiteLLMBackend and LiteLLM's bundled local price table; no network calls.
    On failure, first check: backend._litellm_cost and LiteLLM's cost_per_token.
    """
    known = await LiteLLMBackend(completion_call=Recorder(_response(_hidden_params={}))).execute(
        _request(model_id="gpt-4o-mini")
    )
    assert known.computed_cost_usd is not None
    assert known.computed_cost_usd > 0
    unknown = await LiteLLMBackend(completion_call=Recorder(_response(_hidden_params={}))).execute(
        _request(model_id="no-such-provider/no-such-model")
    )
    assert unknown.computed_cost_usd is None


@pytest.mark.mock
@pytest.mark.parametrize(
    ("error", "expected", "category"),
    [
        (litellm.Timeout(message=f"t {SECRET}", model="m", llm_provider="p"), ExecutionTimeoutError, "timeout"),
        (
            litellm.AuthenticationError(message=f"bad key {SECRET}", llm_provider="p", model="m"),
            ExecutionAuthenticationError,
            "authentication",
        ),
        (
            litellm.RateLimitError(message=f"slow {SECRET}", llm_provider="p", model="m"),
            ExecutionRateLimitError,
            "rate_limit",
        ),
        (
            litellm.ContextWindowExceededError(message=f"long {SECRET}", model="m", llm_provider="p"),
            ExecutionContextError,
            "context_length",
        ),
        (
            litellm.APIError(status_code=500, message=f"boom {SECRET}", llm_provider="p", model="m"),
            ExecutionProviderError,
            "provider_error",
        ),
        (RuntimeError(f"generic {SECRET}"), ExecutionProviderError, "provider_error"),
        (TimeoutError(f"builtin {SECRET}"), ExecutionTimeoutError, "timeout"),
    ],
)
async def test_provider_exceptions_map_to_project_errors(error: Exception, expected: type, category: str):
    """[Local] failure mapping: LiteLLM and generic exceptions become sanitized project errors with latency.

    Scenario: The mocked completion raises real LiteLLM exception types carrying a secret in their text.
    Boundaries: Real LiteLLMBackend and real litellm exception classes; no network.
    On failure, first check: errors.classify_exception and backend._failure_types.
    """
    with pytest.raises(expected) as raised:
        await LiteLLMBackend(completion_call=Recorder(error), api_key=SECRET).execute(_request())
    assert raised.value.category == category
    assert raised.value.latency_ms is not None
    assert SECRET not in str(raised.value)
    assert SECRET not in repr(raised.value)
    assert raised.value.__cause__ is None
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.mock
@pytest.mark.parametrize(
    "payload",
    [{"choices": []}, {}, {"choices": [None]}, {"choices": [{"finish_reason": "stop"}]}],
)
async def test_malformed_response_is_a_project_error(payload: dict[str, Any]):
    """[Local] malformed response: unusable provider payloads raise MalformedResponseError, not raw errors.

    Scenario: The mocked completion returns absent/empty choices or a choice without a message.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend.execute normalization error handling.
    """
    with pytest.raises(MalformedResponseError) as raised:
        await LiteLLMBackend(completion_call=Recorder(payload)).execute(_request())
    assert raised.value.category == "malformed_response"
    assert raised.value.latency_ms is not None


@pytest.mark.mock
async def test_nonsense_usage_is_tolerated_as_unavailable():
    """[Local] tolerant usage: an unusable usage payload degrades to unknown usage instead of failing the call.

    Scenario: The response is fine but its usage is a bare string.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: backend._normalize_usage with non-mapping usage.
    """
    result = await LiteLLMBackend(completion_call=Recorder(_response(usage="not-a-mapping"))).execute(_request())
    assert result.output_text == "hello"
    assert result.input_tokens is None


@pytest.mark.mock
async def test_content_variants_and_tool_calls_preserved():
    """[Local] payload fidelity: structured content and tool calls survive normalization.

    Scenario: The response has list content, then JSON content, then tool calls without text.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend._normalize content and tool-call extraction.
    """
    listed = await LiteLLMBackend(
        completion_call=Recorder({"choices": [{"message": {"content": [{"type": "text", "text": "ok"}]}}]})
    ).execute(_request())
    assert json.loads(listed.output_text) == [{"text": "ok", "type": "text"}]

    structured = await LiteLLMBackend(
        completion_call=Recorder(
            _response(choices=[{"message": {"content": '{"answer": 4}'}, "finish_reason": "stop"}])
        )
    ).execute(_request(response_format={"type": "json_schema", "json_schema": {"name": "a", "schema": {}}}))
    assert json.loads(structured.output_text) == {"answer": 4}

    tool_call = {"id": "c1", "type": "function", "function": {"name": "get", "arguments": '{"x": 1}'}}
    tools = await LiteLLMBackend(
        completion_call=Recorder(
            _response(
                choices=[{"message": {"content": None, "tool_calls": [tool_call]}, "finish_reason": "tool_calls"}]
            )
        )
    ).execute(_request())
    assert tools.output_text == ""
    assert tools.tool_calls == [tool_call]
    assert tools.status is ExecutionStatus.COMPLETED


@pytest.mark.mock
async def test_request_options_are_forwarded_to_litellm():
    """[Local] request forwarding: tools, response_format, parameters, and routing reach LiteLLM intact.

    Scenario: Execute a request with tools, structured output, parameters, and provider routing.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend._build_kwargs.
    """
    recorder = Recorder(_response())
    tools = [{"type": "function", "function": {"name": "f", "parameters": {}}}]
    response_format = {"type": "json_object"}
    request = _request(
        tools=tools,
        response_format=response_format,
        parameters={"temperature": 0, "max_tokens": 9, "extra_body": {"transforms": ["x"]}},
        provider_routing={"order": ["acme"], "allow_fallbacks": False},
        metadata={"trace_id": "trace-1"},
    )
    await LiteLLMBackend(completion_call=recorder, api_key=SECRET, max_retries=2).execute(request)
    sent = recorder.calls[0]
    assert sent["tools"] == tools
    assert sent["response_format"] == response_format
    assert sent["temperature"] == 0
    assert sent["max_tokens"] == 9
    assert sent["extra_body"] == {"transforms": ["x"], "provider": {"order": ["acme"], "allow_fallbacks": False}}
    assert sent["num_retries"] == 2
    assert sent["api_key"] == SECRET
    assert sent["metadata"] == {"trace_id": "trace-1"}
    assert "stream" not in sent


@pytest.mark.mock
@pytest.mark.parametrize(
    ("field", "invalid_data"),
    [
        ("parameters", {"api_key": SECRET}),
        ("parameters", {"fallbacks": ["other"]}),
        ("metadata", {"api_key": SECRET}),
    ],
)
async def test_mutated_request_data_is_revalidated_before_execution(field: str, invalid_data: dict[str, Any]):
    """[Local] request boundary: nested mutations cannot bypass credential or fallback checks.

    Scenario: Mutate a frozen request's nested mapping after construction, then execute it.
    Boundaries: Real LiteLLMBackend with a recording completion double; no network.
    On failure, first check: execute's request revalidation before call construction.
    """
    recorder = Recorder(_response())
    request = _request()
    getattr(request, field).update(invalid_data)
    with pytest.raises(ValidationError):
        await LiteLLMBackend(completion_call=recorder).execute(request)
    assert recorder.calls == []


@pytest.mark.mock
async def test_retries_are_bounded_and_reported():
    """[Local] retries: count is validated, config-controlled, and reported in metadata.

    Scenario: Build backends with out-of-range retries; a request tries to inject num_retries.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend.__init__ validation and _build_kwargs.
    """
    for bad in (-1, backend_module.MAX_RETRIES_LIMIT + 1):
        with pytest.raises(ConfigurationError):
            LiteLLMBackend(max_retries=bad)
    recorder = Recorder(_response())
    result = await LiteLLMBackend(completion_call=recorder, max_retries=3).execute(_request())
    assert recorder.calls[0]["num_retries"] == 3
    assert result.metadata["max_retries"] == 3

    recorder = Recorder(_response())
    await LiteLLMBackend(completion_call=recorder).execute(_request(parameters={"num_retries": 99}))
    assert "num_retries" not in recorder.calls[0]


@pytest.mark.mock
async def test_secrets_are_not_leaked():
    """[Local] secret redaction: the API key never appears in results, errors, observations, or repr.

    Scenario: Execute with an API key on success and failure; inspect every output surface.
    Boundaries: Real LiteLLMBackend; the LiteLLM call is an injected double, no network.
    On failure, first check: LiteLLMBackend.__repr__, classify_exception, and to_stored_observation.
    """
    backend = LiteLLMBackend(completion_call=Recorder(_response()), api_key=SECRET)
    assert SECRET not in repr(backend)
    assert "api_key=set" in repr(backend)
    assert "api_key=unset" in repr(LiteLLMBackend())
    result = await backend.execute(_request())
    assert SECRET not in result.model_dump_json()
    assert SECRET not in result.to_stored_observation().model_dump_json()
    with pytest.raises(ExecutionAuthenticationError) as raised:
        await LiteLLMBackend(
            completion_call=Recorder(litellm.AuthenticationError(message="******", llm_provider="p", model="m")),
            api_key=SECRET,
        ).execute(_request())
    assert SECRET not in str(raised.value)
    assert SECRET not in json.dumps(raised.value.args)


class _Stream:
    """Async iterator over scripted chunks that may raise partway through."""

    def __init__(self, chunks: list[Any], error: Optional[Exception] = None):
        """Store the chunks to yield and an optional error raised after them."""
        self._chunks = chunks
        self._error = error

    def __aiter__(self) -> AsyncIterator[Any]:
        """Return the async iterator."""
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[Any]:
        """Yield chunks, then raise the scripted error if any."""
        for chunk in self._chunks:
            yield chunk
        if self._error is not None:
            raise self._error


def _chunk(
    content: Optional[str] = None, *, finish: Optional[str] = None, usage: Any = None, **extra: Any
) -> dict[str, Any]:
    """Build a streaming chunk payload."""
    return {"choices": [{"delta": {"content": content, **extra}, "finish_reason": finish}], "usage": usage}


@pytest.mark.mock
async def test_streaming_aggregates_text_usage_and_ttft():
    """[Local] streaming: text is aggregated, TTFT measured, usage and finish reason captured at the end.

    Scenario: A mocked stream yields an empty role chunk, two text chunks, and a final usage chunk.
    Boundaries: Real LiteLLMBackend; the LiteLLM stream is an injected double, no network.
    On failure, first check: LiteLLMBackend._execute_stream.
    """
    deltas: list[str] = []
    stream = _Stream(
        [
            _chunk(None),
            _chunk("Hel"),
            _chunk("lo", finish="stop"),
            {"choices": [], "usage": {"prompt_tokens": 4, "completion_tokens": 2, "total_tokens": 6}},
        ]
    )
    recorder = Recorder(stream)
    result = await LiteLLMBackend(completion_call=recorder, cost_call=_cost, on_text_delta=deltas.append).execute(
        _request(stream=True)
    )
    assert recorder.calls[0]["stream"] is True
    assert recorder.calls[0]["stream_options"] == {"include_usage": True}
    assert result.streamed is True
    assert result.output_text == "Hello"
    assert deltas == ["Hel", "lo"]
    assert result.time_to_first_token_ms is not None
    assert 0 <= result.time_to_first_token_ms <= result.latency_ms
    assert result.finish_reason == "stop"
    assert result.usage is not None
    assert result.usage.total_tokens == 6
    assert result.computed_cost_usd == Decimal("0.006")
    assert result.to_stored_observation().time_to_first_token_ms is not None


@pytest.mark.mock
async def test_streaming_tool_call_fragments_are_merged():
    """[Local] streaming tools: fragmented tool-call deltas are merged per call index.

    Scenario: A stream delivers a tool call's name and arguments across several chunks.
    Boundaries: Real LiteLLMBackend; the LiteLLM stream is an injected double, no network.
    On failure, first check: backend._merge_tool_fragment.
    """
    stream = _Stream(
        [
            _chunk(tool_calls=[{"index": 0, "id": "c1", "function": {"name": "get_", "arguments": '{"x"'}}]),
            _chunk(tool_calls=[{"index": 0, "function": {"name": "weather", "arguments": ": 1}"}}]),
            _chunk(tool_calls=[SimpleNamespace(index="bad", id=None, function=None)], finish="tool_calls"),
        ]
    )
    result = await LiteLLMBackend(completion_call=Recorder(stream)).execute(_request(stream=True))
    assert result.output_text == ""
    assert result.tool_calls[0]["id"] == "c1"
    assert result.tool_calls[0]["function"] == {"name": "get_weather", "arguments": '{"x": 1}'}
    assert result.status is ExecutionStatus.COMPLETED


@pytest.mark.mock
async def test_streaming_hidden_cost_is_actual():
    """[Local] streaming cost: a response cost exposed on the final chunk is recorded as actual.

    Scenario: The last stream chunk carries _hidden_params.response_cost.
    Boundaries: Real LiteLLMBackend; the LiteLLM stream is an injected double, no network.
    On failure, first check: backend._execute_stream hidden-params capture.
    """
    stream = _Stream([_chunk("a"), {**_chunk("b", finish="stop"), "_hidden_params": {"response_cost": "0.5"}}])
    result = await LiteLLMBackend(completion_call=Recorder(stream)).execute(_request(stream=True))
    assert result.actual_cost_usd == Decimal("0.5")
    assert result.usage is None


@pytest.mark.mock
async def test_stream_error_after_output_is_partial():
    """[Local] streaming partial failure: an error after output raises PartialOutputError, clearly marked.

    Scenario: A stream yields text and then fails with a timeout carrying a secret.
    Boundaries: Real LiteLLMBackend; the LiteLLM stream is an injected double, no network.
    On failure, first check: LiteLLMBackend._execute_stream error branch.
    """
    stream = _Stream([_chunk("par"), _chunk("tial")], error=TimeoutError(SECRET))
    with pytest.raises(PartialOutputError) as raised:
        await LiteLLMBackend(completion_call=Recorder(stream)).execute(_request(stream=True))
    assert raised.value.category == "partial_output"
    assert raised.value.partial_output == "partial"
    assert raised.value.time_to_first_token_ms is not None
    assert raised.value.latency_ms is not None
    assert SECRET not in str(raised.value)
    assert raised.value.__cause__ is None
    assert SECRET not in "".join(traceback.format_exception(raised.value))


@pytest.mark.mock
@pytest.mark.parametrize("with_output", [False, True])
async def test_malformed_stream_chunk_uses_project_error(with_output: bool):
    """[Local] malformed streaming: bad tool fragments become a sanitized malformed or partial-output error.

    Scenario: A chunk has a malformed choices payload, before or after streamed text.
    Boundaries: Real LiteLLMBackend and an in-memory stream double; no network.
    On failure, first check: _execute_stream malformed-chunk normalization.
    """
    chunks = [_chunk("partial")] if with_output else []
    chunks.append({"choices": "not-a-sequence"})
    expected = PartialOutputError if with_output else MalformedResponseError
    with pytest.raises(expected) as raised:
        await LiteLLMBackend(completion_call=Recorder(_Stream(chunks))).execute(_request(stream=True))
    assert raised.value.category == ("partial_output" if with_output else "malformed_response")
    if with_output:
        assert isinstance(raised.value, PartialOutputError)
        assert raised.value.partial_output == "partial"
    assert raised.value.latency_ms is not None


@pytest.mark.mock
async def test_stream_final_result_validation_error_is_normalized(monkeypatch: pytest.MonkeyPatch):
    """[Local] malformed streaming result: final validation failures preserve prior output as partial.

    Scenario: Result construction raises a validation error after a text chunk was received.
    Boundaries: Real LiteLLMBackend with only its result builder replaced; no network.
    On failure, first check: _execute_stream final result normalization.
    """
    backend = LiteLLMBackend(completion_call=Recorder(_Stream([_chunk("partial")])))

    def invalid_result(*args: Any, **kwargs: Any) -> Any:
        """Simulate a final DTO validation failure."""
        raise ValidationError.from_exception_data(
            "ExecutionResult", [{"type": "missing", "loc": ("output_text",), "input": {}}]
        )

    monkeypatch.setattr(backend, "_build_result", invalid_result)
    with pytest.raises(PartialOutputError) as raised:
        await backend.execute(_request(stream=True))
    assert raised.value.partial_output == "partial"


@pytest.mark.mock
async def test_stream_error_before_output_and_connect_failure_are_classified():
    """[Local] streaming early failure: failures before any output use the ordinary taxonomy.

    Scenario: A stream fails before output; a separate call fails to open the stream.
    Boundaries: Real LiteLLMBackend; the LiteLLM stream is an injected double, no network.
    On failure, first check: LiteLLMBackend._execute_stream error branch and classify_exception.
    """
    with pytest.raises(ExecutionRateLimitError):
        await LiteLLMBackend(
            completion_call=Recorder(
                _Stream([], error=litellm.RateLimitError(message="x", llm_provider="p", model="m"))
            )
        ).execute(_request(stream=True))
    with pytest.raises(ExecutionTimeoutError):
        await LiteLLMBackend(completion_call=Recorder(TimeoutError("x"))).execute(_request(stream=True))


@pytest.mark.mock
async def test_default_completion_call_resolves_litellm(monkeypatch: pytest.MonkeyPatch):
    """[Local] default wiring: without an injected callable the backend resolves litellm.acompletion.

    Scenario: Replace litellm.acompletion with a double and execute without injecting one; then simulate LiteLLM missing.
    Boundaries: Real LiteLLMBackend; litellm.acompletion is monkeypatched, no network.
    On failure, first check: backend._get_completion_call.
    """
    recorder = Recorder(_response())
    monkeypatch.setattr(litellm, "acompletion", recorder)
    result = await LiteLLMBackend().execute(_request())
    assert result.output_text == "hello"
    assert recorder.calls

    def missing(name: str) -> Any:
        """Pretend LiteLLM cannot be imported."""
        raise ImportError(name)

    monkeypatch.setattr(backend_module.importlib, "import_module", missing)
    with pytest.raises(DependencyError):
        await LiteLLMBackend().execute(_request())
