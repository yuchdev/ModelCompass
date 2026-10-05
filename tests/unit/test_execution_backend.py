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
async def test_litellm_backend_normalizes_usage_without_persisting_messages() -> None:
    calls: list[dict[str, Any]] = []

    async def fake_completion(**kwargs: Any) -> dict[str, Any]:
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
    result = await LiteLLMBackend(
        completion_call=fake_completion, api_key="not-persisted"
    ).complete(request)
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
async def test_litellm_backend_handles_bad_cost_content_and_empty_choices() -> None:
    async def invalid_usage(**kwargs: Any) -> dict[str, Any]:
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
        del kwargs
        return {"choices": []}

    with pytest.raises(ExecutionError, match="no choices"):
        await LiteLLMBackend(completion_call=no_choices).complete(
            CompletionRequest(model_id="m", task="t", messages=[])
        )


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_backend_sanitizes_provider_errors() -> None:
    async def failure(**kwargs: Any) -> None:
        del kwargs
        raise RuntimeError("secret-token should not be printed")

    with pytest.raises(ExecutionError, match="RuntimeError") as raised:
        await LiteLLMBackend(completion_call=failure).complete(
            CompletionRequest(model_id="m", task="t", messages=[])
        )
    assert "secret-token" not in str(raised.value)
    assert raised.value.latency_ms is not None
