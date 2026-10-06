from __future__ import annotations

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import litellm
import pytest

from model_compass.application import AnalyticsFacade
from model_compass.benchmarks import BenchmarkCase, BenchmarkDataset, run_benchmark
from model_compass.domain import (
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
    SupportStatus,
)
from model_compass.exceptions import NoEligibleModelError
from model_compass.execution import (
    ExecutionRateLimitError,
    ExecutionRequest,
    LiteLLMBackend,
    NullObservationSink,
    PartialOutputError,
)
from model_compass.storage import InMemoryObservationStore, SQLiteObservationStore
from tests.fixtures.fake_execution_backend import FakeExecutionBackend


def _profile(name: str, *, prompt_price: str, completion_price: str) -> ModelProfile:
    """Build a text+tools model profile with explicit prices."""
    return ModelProfile(
        identity=ModelIdentity(provider="test", model_id=name, canonical_id=f"test:{name}"),
        capabilities=ModelCapabilities(
            context_length=100_000,
            input_modalities=("text",),
            output_modalities=("text",),
            tools=SupportStatus.SUPPORTED,
            structured_output=SupportStatus.SUPPORTED,
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal(prompt_price)),
                "completion": PriceComponent(key="completion", amount=Decimal(completion_price)),
            }
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )


_PROFILES = [
    _profile("pricey", prompt_price="0.00001", completion_price="0.00002"),
    _profile("cheap", prompt_price="0.000001", completion_price="0.000002"),
]
_REQUEST_PROFILE = RequestProfile(task="qa", explicit_input_tokens=1000, expected_output_tokens=500)
_NOW = datetime(2026, 1, 2, tzinfo=UTC)


class _LiteLLMDouble:
    """Narrow-boundary replacement for litellm.acompletion that records calls."""

    def __init__(self, response: Any = None, error: Optional[Exception] = None):
        """Store the scripted response or error."""
        self.response = response
        self.error = error
        self.calls: list[dict[str, Any]] = []

    async def __call__(self, **kwargs: Any) -> Any:
        """Record the call; raise or return the scripted outcome."""
        self.calls.append(kwargs)
        if self.error is not None:
            raise self.error
        return self.response


def _response(cost: Optional[str] = "0.0018", content: str = "hello", **message: Any) -> dict[str, Any]:
    """Build a completion payload with usage and an optional provider cost."""
    return {
        "choices": [{"message": {"content": content, **message}, "finish_reason": "stop"}],
        "usage": {"prompt_tokens": 1000, "completion_tokens": 400, "total_tokens": 1400},
        "_hidden_params": {"response_cost": cost} if cost is not None else {},
    }


def _execution_request(**overrides: Any) -> ExecutionRequest:
    """Build the execution request whose model id the selector will replace."""
    fields: dict[str, Any] = {
        "model_id": "placeholder",
        "task": "qa",
        "messages": [{"role": "user", "content": "private prompt"}],
        "metadata": {"run": "r1"},
    }
    fields.update(overrides)
    return ExecutionRequest.model_validate(fields)


@pytest.mark.integration
async def test_select_execute_record_and_reconcile_with_sqlite(tmp_path: Path):
    """[Integration] select -> execute -> observe -> reconcile: the whole loop persists one observation.

    Scenario: Select the cheapest of two models, run it through LiteLLMBackend with a mocked LiteLLM call,
        record into a temporary SQLite store, then read the observation back.
    Boundaries: Real selection, LiteLLMBackend, facade, and SQLiteObservationStore (tmp_path); only the
        LiteLLM call is a double, no network.
    On failure, first check: AnalyticsFacade.select_and_execute and ExecutionResult.to_stored_observation.
    """
    store = SQLiteObservationStore(tmp_path / "obs.sqlite3")
    litellm_double = _LiteLLMDouble(_response())
    facade = AnalyticsFacade(observation_store=store)

    outcome = await facade.select_and_execute(
        profiles=_PROFILES,
        request_profile=_REQUEST_PROFILE,
        execution_request=_execution_request(),
        policy="cheapest",
        backend=LiteLLMBackend(completion_call=litellm_double),
        now_utc=_NOW,
    )

    assert outcome.selection.selected is not None
    assert outcome.selection.selected.model_id == "test:cheap"
    assert litellm_double.calls[0]["model"] == "test:cheap"
    assert outcome.execution.model_id == "test:cheap"
    assert outcome.execution.output_text == "hello"
    assert outcome.reconciliation.estimated_before == Decimal("0.002")
    assert outcome.reconciliation.actual_after == Decimal("0.0018")
    assert outcome.reconciliation.absolute_error == Decimal("0.0002")
    assert outcome.reconciliation.relative_error == Decimal("0.0002") / Decimal("0.0018")
    assert outcome.reconciliation.actual_source == "provider_reported"

    [stored] = store.query_observations(model_id="test:cheap")
    assert stored.observation_id == outcome.observation_id
    assert stored.success is True
    assert stored.estimated_cost == Decimal("0.002")
    assert stored.actual_cost == Decimal("0.0018")
    assert (stored.input_tokens, stored.output_tokens) == (1000, 400)
    assert Decimal(stored.metadata["cost_reconciliation"]["absolute_error"]) == Decimal("0.0002")
    assert stored.prompt is None
    assert "private prompt" not in json.dumps(stored.model_dump(mode="json"))
    assert "hello" not in json.dumps(stored.model_dump(mode="json"))
    summary = store.summarize_model("test:cheap", min_samples=1)
    assert summary.cost.cost_basis == "mixed"


@pytest.mark.integration
async def test_missing_actual_cost_gives_incomplete_reconciliation():
    """[Integration] incomplete reconciliation: no provider cost means no error figures, not a zero error.

    Scenario: The mocked LiteLLM response omits its cost; a cost callable computes an estimate.
    Boundaries: Real selection, LiteLLMBackend, facade, and in-memory store; the LiteLLM call is a double.
    On failure, first check: ExecutionResult.reconcile and the facade's reconciliation wiring.
    """
    store = InMemoryObservationStore()
    outcome = await AnalyticsFacade(observation_store=store).select_and_execute(
        profiles=_PROFILES,
        request_profile=_REQUEST_PROFILE,
        execution_request=_execution_request(),
        backend=LiteLLMBackend(
            completion_call=_LiteLLMDouble(_response(cost=None)), cost_call=lambda *_: Decimal("0.0019")
        ),
        now_utc=_NOW,
    )
    assert not outcome.reconciliation.is_complete
    assert outcome.reconciliation.absolute_error is None
    assert outcome.reconciliation.relative_error is None
    assert outcome.execution.computed_cost_usd == Decimal("0.0019")
    [stored] = store.query_observations()
    assert stored.actual_cost is None
    assert stored.estimated_cost == Decimal("0.002")
    assert stored.metadata["computed_cost_usd"] == "0.0019"
    assert stored.metadata["cost_reconciliation"]["complete"] == "false"


@pytest.mark.integration
async def test_rate_limited_execution_is_recorded_and_reraised(tmp_path: Path):
    """[Integration] failure observation: a rate-limit failure is persisted with its category, then re-raised.

    Scenario: The mocked LiteLLM call raises a LiteLLM rate-limit error carrying a secret.
    Boundaries: Real selection, LiteLLMBackend, facade, and SQLiteObservationStore (tmp_path); LiteLLM is a double.
    On failure, first check: AnalyticsFacade.select_and_execute failure branch and failed_observation.
    """

    rate_limit = litellm.RateLimitError(message="sk-leak", llm_provider="p", model="m")
    store = SQLiteObservationStore(tmp_path / "obs.sqlite3")
    with pytest.raises(ExecutionRateLimitError) as raised:
        await AnalyticsFacade(observation_store=store).select_and_execute(
            profiles=_PROFILES,
            request_profile=_REQUEST_PROFILE,
            execution_request=_execution_request(),
            backend=LiteLLMBackend(completion_call=_LiteLLMDouble(error=rate_limit)),
            now_utc=_NOW,
        )
    [stored] = store.query_observations()
    assert raised.value.observation_id == stored.observation_id
    assert stored.success is False
    assert stored.failure_category == "rate_limit"
    assert stored.model_id == "test:cheap"
    assert stored.estimated_cost == Decimal("0.002")
    assert stored.actual_cost is None
    assert stored.latency_ms is not None
    assert "sk-leak" not in json.dumps(stored.model_dump(mode="json"))
    assert store.summarize_model("test:cheap", min_samples=1).reliability.failure_categories == {"rate_limit": 1}


@pytest.mark.integration
async def test_partial_stream_failure_is_recorded_as_partial():
    """[Integration] streaming failure: a stream that dies mid-output is stored as a partial_output failure.

    Scenario: The mocked LiteLLM stream yields one chunk and then raises.
    Boundaries: Real selection, LiteLLMBackend, facade, and in-memory store; the LiteLLM stream is a double.
    On failure, first check: LiteLLMBackend._execute_stream and failed_observation partial marking.
    """

    class Broken:
        """Stream yielding one chunk before failing."""

        def __aiter__(self) -> AsyncIterator[Any]:
            """Return the async iterator."""
            return self._iterate()

        async def _iterate(self) -> AsyncIterator[Any]:
            """Yield one text chunk then raise."""
            yield {"choices": [{"delta": {"content": "half"}, "finish_reason": None}]}
            raise ConnectionError("dropped")

    store = InMemoryObservationStore()
    with pytest.raises(PartialOutputError):
        await AnalyticsFacade(observation_store=store).select_and_execute(
            profiles=_PROFILES,
            request_profile=_REQUEST_PROFILE,
            execution_request=_execution_request(stream=True),
            backend=LiteLLMBackend(completion_call=_LiteLLMDouble(Broken())),
            now_utc=_NOW,
        )
    [stored] = store.query_observations()
    assert stored.failure_category == "partial_output"
    assert stored.metadata["partial_output"] is True
    assert stored.time_to_first_token_ms is not None
    assert "half" not in json.dumps(stored.model_dump(mode="json"))


@pytest.mark.integration
async def test_null_sink_executes_without_persisting():
    """[Integration] no persistence: a null sink executes and reconciles but writes nothing.

    Scenario: Run select_and_execute with NullObservationSink while an in-memory store holds selection evidence.
    Boundaries: Real selection, LiteLLMBackend, and facade; the LiteLLM call is a double, no I/O.
    On failure, first check: the observation_sink handling in AnalyticsFacade.select_and_execute.
    """
    store = InMemoryObservationStore()
    outcome = await AnalyticsFacade(observation_store=store).select_and_execute(
        profiles=_PROFILES,
        request_profile=_REQUEST_PROFILE,
        execution_request=_execution_request(),
        backend=FakeExecutionBackend(cost_usd=Decimal("0.0015")),
        observation_sink=NullObservationSink(),
        now_utc=_NOW,
    )
    assert store.query_observations() == []
    assert outcome.reconciliation.actual_after == Decimal("0.0015")
    assert outcome.observation_id


@pytest.mark.integration
async def test_no_eligible_model_raises_before_executing():
    """[Integration] selection gate: when no model is eligible, nothing is executed or recorded.

    Scenario: Require a context length no candidate has, with a fake backend that records calls.
    Boundaries: Real selection and facade; the backend is a local fake, no I/O.
    On failure, first check: AnalyticsFacade.select_and_execute and select(raise_on_empty=True).
    """
    backend = FakeExecutionBackend()
    store = InMemoryObservationStore()
    with pytest.raises(NoEligibleModelError):
        await AnalyticsFacade(observation_store=store).select_and_execute(
            profiles=_PROFILES,
            request_profile=_REQUEST_PROFILE,
            execution_request=_execution_request(),
            backend=backend,
            minimum_context=10_000_000,
            now_utc=_NOW,
        )
    assert backend.calls == []
    assert store.query_observations() == []


@pytest.mark.integration
async def test_structured_output_and_tool_payload_preserved_end_to_end():
    """[Integration] payload fidelity: tools and response_format reach LiteLLM and tool calls come back intact.

    Scenario: Execute a request with tools and a JSON schema; the mocked response returns a tool call.
    Boundaries: Real selection, LiteLLMBackend, and facade; the LiteLLM call is a double, no network.
    On failure, first check: LiteLLMBackend._build_kwargs and tool-call normalization.
    """
    tools = [{"type": "function", "function": {"name": "lookup", "parameters": {"type": "object"}}}]
    schema = {"type": "json_schema", "json_schema": {"name": "answer", "schema": {"type": "object"}}}
    tool_call = {"id": "t1", "type": "function", "function": {"name": "lookup", "arguments": '{"q": "x"}'}}
    litellm_double = _LiteLLMDouble(_response(content='{"ok": true}', tool_calls=[tool_call]))
    outcome = await AnalyticsFacade(observation_store=InMemoryObservationStore()).select_and_execute(
        profiles=_PROFILES,
        request_profile=_REQUEST_PROFILE,
        execution_request=_execution_request(tools=tools, response_format=schema),
        backend=LiteLLMBackend(completion_call=litellm_double),
        now_utc=_NOW,
    )
    sent = litellm_double.calls[0]
    assert sent["tools"] == tools
    assert sent["response_format"] == schema
    assert json.loads(outcome.execution.output_text) == {"ok": True}
    assert outcome.execution.tool_calls == [tool_call]


@pytest.mark.integration
async def test_benchmark_runner_works_with_litellm_backend_mock():
    """[Integration] benchmark runner: run_benchmark drives LiteLLMBackend and settles on its actual cost.

    Scenario: Run a one-case dataset against two models through LiteLLMBackend with a mocked LiteLLM call.
    Boundaries: Real dataset, runner, evaluator, and LiteLLMBackend; only the LiteLLM call is a double.
    On failure, first check: benchmarks.runner calling backend.execute and reading actual_cost_usd.
    """
    dataset = BenchmarkDataset(
        name="smoke",
        version="1",
        cases=(BenchmarkCase(case_id="c", task="qa", input_text="2+2?", evaluator="exact", expected_output="4"),),
    )
    litellm_double = _LiteLLMDouble(_response(cost="0.01", content="4"))
    outcome = await run_benchmark(dataset, ["test:a", "test:b"], backend=LiteLLMBackend(completion_call=litellm_double))
    assert {call["model"] for call in litellm_double.calls} == {"test:a", "test:b"}
    assert [result.score for result in outcome.results] == [Decimal(1), Decimal(1)]
    assert all(result.cost == Decimal("0.01") for result in outcome.results)
