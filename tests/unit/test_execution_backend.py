from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from model_compass.execution import (
    CompletionRequest,
    ExecutionError,
    LiteLLMBackend,
)


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_backend_normalizes_usage_without_persisting_messages():
    """[Unit] usage normalization: verifies completion usage is normalized without persisting messages.

    Scenario: Inject a fake completion callable returning usage and cost fields, then
        complete a request and convert the result to an observation.
    Boundaries: Pure normalization logic; the completion callable is a local fake, no network.
    On failure, first check: If this fails, check LiteLLMBackend.complete's usage/cost
        extraction and ExecutionResult.to_observation's field selection.
    """
    calls: list[dict[str, Any]] = []

    async def fake_completion(**kwargs: Any) -> dict[str, Any]:
        """Record the call's kwargs and return a well-formed completion payload."""
        calls.append(kwargs)
        return {
            "choices": [{"message": {"content": "done"}}],
            "usage": {"prompt_tokens": 12, "completion_tokens": 3},
            "_hidden_params": {"response_cost": "0.000042"},
        }

    request = CompletionRequest(
        model_id="provider/model",
        task="summarization",
        messages=[{"role": "user", "content": "private input"}],
    )
    result = await LiteLLMBackend(completion_call=fake_completion, api_key="not-persisted").complete(request)
    observation = result.to_observation()

    assert result.output_text == "done"
    assert result.input_tokens == 12
    assert result.output_tokens == 3
    assert result.actual_cost_usd == Decimal("0.000042")
    assert result.latency_ms >= 0
    assert calls[0]["api_key"] == "not-persisted"
    assert "messages" not in observation.model_dump()
    assert observation.actual_cost_usd == Decimal("0.000042")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_backend_handles_bad_cost_content_and_empty_choices():
    """[Unit] malformed response handling: verifies bad cost/content and empty choices are handled.

    Scenario: Complete requests against fakes returning non-numeric cost, list-typed
        content, and an empty choices list.
    Boundaries: Pure normalization logic; both completion callables are local fakes.
    On failure, first check: If this fails, check LiteLLMBackend.complete's content/cost
        coercion and its "no choices" ExecutionError.
    """

    async def invalid_usage(**kwargs: Any) -> dict[str, Any]:
        """Return a payload with list-typed content and a non-numeric cost."""
        del kwargs
        return {
            "choices": [{"message": {"content": [{"type": "text", "text": "ok"}]}}],
            "_hidden_params": {"response_cost": "NaN"},
        }

    result = await LiteLLMBackend(completion_call=invalid_usage).complete(
        CompletionRequest(model_id="m", task="t", messages=[])
    )
    assert result.output_text == '[{"text": "ok", "type": "text"}]'
    assert result.actual_cost_usd is None
    assert result.input_tokens is None

    async def no_choices(**kwargs: Any) -> dict[str, Any]:
        """Return a completion payload with no choices."""
        del kwargs
        return {"choices": []}

    with pytest.raises(ExecutionError, match="no choices"):
        await LiteLLMBackend(completion_call=no_choices).complete(
            CompletionRequest(model_id="m", task="t", messages=[])
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_backend_sanitizes_provider_errors():
    """[Unit] error sanitization: verifies a known provider failure is wrapped without leaking its message.

    Scenario: Inject a fake completion callable that raises TimeoutError carrying a
        sensitive string, then complete a request.
    Boundaries: Pure error-handling logic; the completion callable is a local fake, no network.
    On failure, first check: If this fails, check LiteLLMBackend.complete's except clause
        and that it raises ExecutionError with only the exception type name, not its message.
    """

    async def failure(**kwargs: Any):
        """Simulate a known provider failure carrying a sensitive message."""
        del kwargs
        raise TimeoutError("secret-token should not be printed")

    with pytest.raises(ExecutionError, match="TimeoutError") as raised:
        await LiteLLMBackend(completion_call=failure).complete(CompletionRequest(model_id="m", task="t", messages=[]))
    assert "secret-token" not in str(raised.value)
    assert raised.value.latency_ms is not None
