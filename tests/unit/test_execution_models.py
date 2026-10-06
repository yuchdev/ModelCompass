from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
from pydantic import ValidationError

from model_compass.execution import (
    CostReconciliation,
    ExecutionAuthenticationError,
    ExecutionBadRequestError,
    ExecutionConnectionError,
    ExecutionContextError,
    ExecutionError,
    ExecutionProviderError,
    ExecutionRateLimitError,
    ExecutionRequest,
    ExecutionResult,
    ExecutionStatus,
    ExecutionTimeoutError,
    NullObservationSink,
    PartialOutputError,
    UsageRecord,
    classify_exception,
    failed_observation,
    reconcile_costs,
)
from model_compass.execution.models import status_from_finish_reason


def _request(**overrides: object) -> ExecutionRequest:
    """Build a minimal valid request, applying field overrides."""
    fields: dict[str, object] = {"model_id": "m", "task": "qa", "messages": [{"role": "user", "content": "hi"}]}
    fields.update(overrides)
    return ExecutionRequest.model_validate(fields)


@pytest.mark.unit
def test_request_defaults_and_from_prompt():
    """[Unit] request construction: optional fields default to absent and from_prompt builds one message.

    Scenario: Build a request directly and via from_prompt.
    Boundaries: Pure pydantic model; no I/O.
    On failure, first check: ExecutionRequest field defaults and from_prompt.
    """
    request = ExecutionRequest.from_prompt("m", "qa", "hello", stream=True)
    assert request.messages == [{"role": "user", "content": "hello"}]
    assert request.stream is True
    assert request.tools is None
    assert request.response_format is None
    assert request.provider_routing is None
    assert request.metadata == {}
    assert _request().stream is False


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"parameters": {"api_key": "sk-secret"}},
        {"parameters": {"extra_headers": {"Authorization": "******"}}},
        {"parameters": {"extra_body": {"X-Api-Key": "abc"}}},
        {"parameters": {"openai_api_key": "abc"}},
        {"provider_routing": {"password": "abc"}},
        {"tools": [{"type": "function", "access_token": "abc"}]},
    ],
)
def test_request_rejects_credentials(overrides: dict[str, object]):
    """[Unit] request secrecy: credential-like keys cannot live in a serializable request.

    Scenario: Build requests carrying credentials in parameters, headers, routing, or tools.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: _contains_secret_key and the ExecutionRequest validators.
    """
    with pytest.raises(ValidationError, match="credential-like"):
        _request(**overrides)


@pytest.mark.unit
def test_request_allows_token_limits_that_look_like_secrets():
    """[Unit] request secrecy: max_tokens is not mistaken for a credential.

    Scenario: Build a request with max_tokens and temperature parameters.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: the exact-match key set in models._SECRET_KEYS.
    """
    request = _request(parameters={"max_tokens": 10, "temperature": 0})
    assert request.parameters["max_tokens"] == 10


@pytest.mark.unit
@pytest.mark.parametrize(
    "overrides",
    [
        {"parameters": {"fallbacks": ["other"]}},
        {"parameters": {"extra_body": {"models": ["a", "b"]}}},
        {"provider_routing": {"route": "fallback"}},
    ],
)
def test_request_rejects_implicit_model_fallback(overrides: dict[str, object]):
    """[Unit] no hidden fallback: parameters that switch models behind the caller are rejected.

    Scenario: Build requests asking LiteLLM/OpenRouter for multi-model fallback.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: _FALLBACK_KEYS and ExecutionRequest._no_hidden_fallbacks.
    """
    with pytest.raises(ValidationError, match="fallback"):
        _request(**overrides)


@pytest.mark.unit
def test_request_serialization_round_trip_has_no_secret_fields():
    """[Unit] request serialization: dumping a request exposes only request data.

    Scenario: Dump a fully populated request to JSON-compatible data and rebuild it.
    Boundaries: Pure pydantic model; no I/O.
    On failure, first check: ExecutionRequest field list; no credential field may be added.
    """
    request = _request(
        tools=[{"type": "function", "function": {"name": "f"}}],
        response_format={"type": "json_object"},
        provider_routing={"order": ["a"]},
        metadata={"run": "1"},
    )
    dumped = request.model_dump(mode="json")
    assert ExecutionRequest.model_validate(dumped) == request
    assert not {key for key in dumped if "key" in key or "secret" in key}


@pytest.mark.unit
def test_usage_record_accepts_unavailable_fields_and_provider_accounting():
    """[Unit] usage invariants: missing fields are fine and unusual accounting is not rejected.

    Scenario: Build empty usage, usage with cache+reasoning above input/output, and a bad total.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: UsageRecord._total_covers_parts.
    """
    assert UsageRecord().total_tokens is None
    unusual = UsageRecord(input_tokens=10, output_tokens=5, total_tokens=15, cached_read_tokens=50, reasoning_tokens=40)
    assert unusual.cached_read_tokens == 50
    with pytest.raises(ValidationError):
        UsageRecord(input_tokens=10, total_tokens=5)
    with pytest.raises(ValidationError):
        UsageRecord(output_tokens=-1)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("finish_reason", "status"),
    [
        ("stop", ExecutionStatus.COMPLETED),
        ("tool_calls", ExecutionStatus.COMPLETED),
        ("length", ExecutionStatus.TRUNCATED),
        ("content_filter", ExecutionStatus.CONTENT_FILTERED),
        ("weird", ExecutionStatus.UNKNOWN),
        (None, ExecutionStatus.UNKNOWN),
    ],
)
def test_status_from_finish_reason(finish_reason: str, status: ExecutionStatus):
    """[Unit] completion status: finish reasons map to a stable status.

    Scenario: Map each representative finish reason.
    Boundaries: Pure function; no I/O.
    On failure, first check: status_from_finish_reason.
    """
    assert status_from_finish_reason(finish_reason) is status


@pytest.mark.unit
def test_reconcile_costs_complete():
    """[Unit] cost reconciliation: both sides present yields absolute and relative error.

    Scenario: Reconcile an estimate of 0.012 against an actual 0.010.
    Boundaries: Pure Decimal arithmetic; no I/O.
    On failure, first check: reconcile_costs error formulas (relative to actual).
    """
    result = reconcile_costs(Decimal("0.012"), Decimal("0.010"), actual_source="provider_reported")
    assert result.is_complete
    assert result.absolute_error == Decimal("0.002")
    assert result.relative_error == Decimal("0.2")
    assert result.actual_source == "provider_reported"
    assert result.to_metadata()["complete"] == "true"


@pytest.mark.unit
@pytest.mark.parametrize(("estimated", "actual"), [(None, Decimal("1")), (Decimal("1"), None), (None, None)])
def test_reconcile_costs_incomplete_is_not_zero_error(estimated: Decimal, actual: Decimal):
    """[Unit] cost reconciliation: a missing side is incomplete, never a zero error.

    Scenario: Reconcile with the estimate, the actual, or both missing.
    Boundaries: Pure Decimal arithmetic; no I/O.
    On failure, first check: reconcile_costs returning 0 instead of None for missing data.
    """
    result = reconcile_costs(estimated, actual, actual_source="x")
    assert not result.is_complete
    assert result.absolute_error is None
    assert result.relative_error is None
    assert result.to_metadata()["complete"] == "false"
    if actual is None:
        assert result.actual_source is None


@pytest.mark.unit
def test_reconcile_costs_zero_actual():
    """[Unit] cost reconciliation: zero actual cost has defined relative error only for a zero estimate.

    Scenario: Reconcile against a free (zero) actual cost with zero and nonzero estimates.
    Boundaries: Pure Decimal arithmetic; no I/O.
    On failure, first check: the division guard in reconcile_costs.
    """
    exact = reconcile_costs(Decimal(0), Decimal(0))
    assert exact.absolute_error == 0
    assert exact.relative_error == 0
    undefined = reconcile_costs(Decimal("0.5"), Decimal(0))
    assert undefined.absolute_error == Decimal("0.5")
    assert undefined.relative_error is None


@pytest.mark.unit
def test_result_to_stored_observation_keeps_actual_and_estimated_separate():
    """[Unit] observation mapping: actual cost, estimate, usage, and reconciliation land in distinct fields.

    Scenario: Convert a result with full usage and both costs into a stored observation.
    Boundaries: Pure model conversion; no I/O.
    On failure, first check: ExecutionResult.to_stored_observation.
    """
    result = ExecutionResult(
        model_id="m",
        task="qa",
        output_text="private output",
        latency_ms=40,
        usage=UsageRecord(input_tokens=10, output_tokens=5, cached_read_tokens=2, reasoning_tokens=1),
        actual_cost_usd=Decimal("0.01"),
        computed_cost_usd=Decimal("0.02"),
        cost_source="provider_reported",
        finish_reason="stop",
        time_to_first_token_ms=7,
        streamed=True,
        metadata={"max_retries": 2, "ignored": "x"},
    )
    stored = result.to_stored_observation(estimated_before=Decimal("0.012"))
    assert stored.success is True
    assert (stored.input_tokens, stored.output_tokens) == (10, 5)
    assert (stored.cached_read_tokens, stored.reasoning_tokens) == (2, 1)
    assert stored.actual_cost == Decimal("0.01")
    assert stored.estimated_cost == Decimal("0.012")
    assert stored.cost_source == "provider_reported"
    assert stored.time_to_first_token_ms == Decimal(7)
    assert stored.finish_reason == "stop"
    assert stored.prompt is None
    assert stored.response is None
    assert stored.metadata["computed_cost_usd"] == "0.02"
    assert stored.metadata["max_retries"] == 2
    assert "ignored" not in stored.metadata
    assert stored.metadata["cost_reconciliation"]["absolute_error"] == "0.002"


@pytest.mark.unit
def test_result_without_actual_cost_records_computed_estimate_only():
    """[Unit] observation mapping: with no actual cost, the computed cost is the estimate and actual stays empty.

    Scenario: Convert a result with a computed cost but no actual cost, with and without a pre-estimate.
    Boundaries: Pure model conversion; no I/O.
    On failure, first check: ExecutionResult.to_stored_observation and reconcile.
    """
    result = ExecutionResult(
        model_id="m",
        task="qa",
        output_text="",
        latency_ms=1,
        input_tokens=3,
        output_tokens=4,
        computed_cost_usd=Decimal("0.02"),
        cost_source="computed",
    )
    plain = result.to_stored_observation()
    assert plain.actual_cost is None
    assert plain.estimated_cost == Decimal("0.02")
    assert (plain.input_tokens, plain.output_tokens) == (3, 4)
    assert "cost_reconciliation" not in plain.metadata
    reconciled = result.reconcile(Decimal("0.01"))
    assert not reconciled.is_complete
    assert (
        result.to_stored_observation(estimated_before=Decimal("0.01")).metadata["cost_reconciliation"]["complete"]
        == "false"
    )


@pytest.mark.unit
def test_legacy_observation_conversion_is_unchanged():
    """[Unit] legacy observation: to_observation still yields the prompt-free task observation.

    Scenario: Convert a result to the task-selection observation shape.
    Boundaries: Pure model conversion; no I/O.
    On failure, first check: ExecutionResult.to_observation.
    """
    observation = ExecutionResult(
        model_id="m", task="qa", output_text="x", latency_ms=3, input_tokens=1, output_tokens=2
    ).to_observation()
    assert observation.succeeded is True
    assert observation.latency_ms == 3


@pytest.mark.unit
def test_failed_observation_omits_error_text_and_marks_partial_output():
    """[Unit] failure observation: category and timing are stored, error text and partial output are not.

    Scenario: Build failure observations from a timeout and a partial-output stream error.
    Boundaries: Pure model conversion; no I/O.
    On failure, first check: failed_observation.
    """
    request = _request(stream=True)
    timeout = failed_observation(
        request, ExecutionTimeoutError("secret detail", latency_ms=9), estimated_before=Decimal(1)
    )
    assert timeout.success is False
    assert timeout.failure_category == "timeout"
    assert timeout.latency_ms == Decimal(9)
    assert timeout.estimated_cost == Decimal(1)
    assert "partial_output" not in timeout.metadata
    partial = failed_observation(
        request,
        PartialOutputError("cut", partial_output="half", latency_ms=5, time_to_first_token_ms=2),
    )
    assert partial.failure_category == "partial_output"
    assert partial.metadata["partial_output"] is True
    assert partial.time_to_first_token_ms == Decimal(2)
    assert "half" not in str(partial.model_dump())
    assert failed_observation(request, ExecutionError("x")).latency_ms is None


class AuthenticationError(Exception):
    """Stand-in for a provider authentication error, classified by name."""


class RateLimitError(Exception):
    """Stand-in for a provider rate-limit error, classified by name."""


class ContextWindowExceededError(Exception):
    """Stand-in for a provider context-window error, classified by name."""


class BadRequestError(Exception):
    """Stand-in for a provider bad-request error, classified by name."""


class APIConnectionError(Exception):
    """Stand-in for a provider connection error, classified by name."""


class SubclassedRateLimit(RateLimitError):
    """A provider subclass that must keep its parent's category."""


@pytest.mark.unit
@pytest.mark.parametrize(
    ("exc", "expected", "category"),
    [
        (TimeoutError("sk-leak"), ExecutionTimeoutError, "timeout"),
        (AuthenticationError("sk-leak"), ExecutionAuthenticationError, "authentication"),
        (RateLimitError("sk-leak"), ExecutionRateLimitError, "rate_limit"),
        (SubclassedRateLimit("sk-leak"), ExecutionRateLimitError, "rate_limit"),
        (ContextWindowExceededError("sk-leak"), ExecutionContextError, "context_length"),
        (BadRequestError("sk-leak"), ExecutionBadRequestError, "bad_request"),
        (APIConnectionError("sk-leak"), ExecutionConnectionError, "connection"),
        (ConnectionError("sk-leak"), ExecutionConnectionError, "connection"),
        (RuntimeError("sk-leak"), ExecutionProviderError, "provider_error"),
    ],
)
def test_classify_exception_maps_categories_without_leaking_text(
    exc: Exception, expected: type[ExecutionError], category: str
):
    """[Unit] failure taxonomy: provider exceptions map to project categories with sanitized messages.

    Scenario: Classify representative provider, builtin, and unknown exceptions carrying a secret.
    Boundaries: Pure function; no I/O.
    On failure, first check: errors._BY_NAME and classify_exception.
    """
    error = classify_exception(exc, latency_ms=3)
    assert isinstance(error, expected)
    assert error.category == category
    assert error.latency_ms == 3
    assert "sk-leak" not in str(error)
    assert type(exc).__name__ in str(error)


@pytest.mark.unit
def test_null_sink_returns_observation_without_storing():
    """[Unit] null sink: observations pass through unchanged and nothing is persisted.

    Scenario: Record an observation through the null sink.
    Boundaries: Pure in-process object; no I/O.
    On failure, first check: NullObservationSink.record_observation.
    """
    observation = failed_observation(_request(), ExecutionError("x", latency_ms=1))
    assert NullObservationSink().record_observation(observation) is observation


@pytest.mark.unit
def test_reconciliation_model_is_frozen():
    """[Unit] reconciliation immutability: reconciliation records cannot be mutated after creation.

    Scenario: Attempt to assign to a field of a CostReconciliation.
    Boundaries: Pure pydantic model; no I/O.
    On failure, first check: CostReconciliation model_config frozen=True.
    """
    reconciliation = CostReconciliation()
    with pytest.raises(ValidationError):
        reconciliation.absolute_error = Decimal(1)  # type: ignore[misc]


@pytest.mark.unit
def test_classify_dual_mro_prefers_timeout_over_connection():
    """[Unit] classification precedence: an httpx connect timeout is a timeout, not a generic connection error.

    Scenario: Classify httpx.ConnectTimeout and httpx.ConnectError.
    Boundaries: Pure function over real httpx exception classes; no network.
    On failure, first check: the ordering of errors._BY_NAME (timeouts precede connection errors).
    """
    assert isinstance(classify_exception(httpx.ConnectTimeout("x")), ExecutionTimeoutError)
    assert isinstance(classify_exception(httpx.ConnectError("x")), ExecutionConnectionError)
