"""Deterministic fake execution backend shared by benchmark runner tests."""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from typing import Optional, Union

from model_compass.execution.backend import CompletionRequest, ExecutionError, ExecutionResult


class FakeExecutionBackend:
    """Scripted, no-network completion backend with per-model failure injection."""

    def __init__(
        self,
        responses: Optional[dict[str, Union[str, Callable[[CompletionRequest], str]]]] = None,
        *,
        cost_usd: Decimal = Decimal("0.001"),
        latency_ms: int = 5,
        input_tokens: int = 10,
        output_tokens: int = 5,
        fail_models: frozenset[str] = frozenset(),
    ):
        """Store scripted responses per model id and fixed usage/cost figures."""
        self._responses = responses or {}
        self._cost_usd = cost_usd
        self._latency_ms = latency_ms
        self._input_tokens = input_tokens
        self._output_tokens = output_tokens
        self._fail_models = fail_models
        self.calls: list[CompletionRequest] = []

    async def execute(self, request: CompletionRequest) -> ExecutionResult:
        """Return a scripted response for the request's model, or raise if it's set to fail."""
        self.calls.append(request)
        if request.model_id in self._fail_models:
            raise ExecutionError(f"simulated failure for {request.model_id}", latency_ms=self._latency_ms)
        responder = self._responses.get(request.model_id)
        if callable(responder):
            output_text = responder(request)
        elif isinstance(responder, str):
            output_text = responder
        else:
            last_message = request.messages[-1] if request.messages else {}
            output_text = str(last_message.get("content", ""))
        return ExecutionResult(
            model_id=request.model_id,
            task=request.task,
            output_text=output_text,
            latency_ms=self._latency_ms,
            input_tokens=self._input_tokens,
            output_tokens=self._output_tokens,
            actual_cost_usd=self._cost_usd,
        )
