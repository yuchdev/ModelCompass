from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path
from typing import Optional

import litellm
import pytest

from model_compass.execution import ExecutionRequest, LiteLLMBackend
from model_compass.storage import SQLiteObservationStore


@pytest.mark.live
async def test_live_execution_records_observation_in_temp_db(tmp_path: Path):
    """[E2E] live execution: one tiny prompt to one explicitly named model, recorded in a temporary DB.

    Scenario: Executes a one-token-ish prompt against the model named in MODEL_ANALYTICS_LIVE_MODEL, after
        checking the worst-case cost against MODEL_ANALYTICS_LIVE_MAX_COST_USD, and stores the observation.
    Boundaries: Real LiteLLM HTTP call to the provider of the named model; opt-in via env vars; the database
        lives under tmp_path, never the user's data directory.
    On failure, first check: provider credentials in the environment and response-format drift in usage fields.
    """
    if os.getenv("MODEL_ANALYTICS_LIVE_LLM") != "1":
        pytest.skip("Set MODEL_ANALYTICS_LIVE_LLM=1 to run the live execution test")
    model = os.getenv("MODEL_ANALYTICS_LIVE_MODEL")
    if not model:
        pytest.skip("Set MODEL_ANALYTICS_LIVE_MODEL to an explicit LiteLLM model id; no model is chosen implicitly")
    ceiling = Decimal(os.getenv("MODEL_ANALYTICS_LIVE_MAX_COST_USD", "0.01"))
    max_tokens = 16
    backend = LiteLLMBackend()
    request = ExecutionRequest.from_prompt(
        model, "live-smoke", "Reply with the single word: ok", parameters={"max_tokens": max_tokens}
    )
    worst_case = _worst_case_cost_usd(model, max_tokens)
    if worst_case is None:
        pytest.skip(f"Cannot determine worst-case cost for {model!r}; refusing an unguarded live request")
    if worst_case > ceiling:
        pytest.skip(f"Worst-case cost {worst_case} exceeds MODEL_ANALYTICS_LIVE_MAX_COST_USD={ceiling}")

    result = await backend.execute(request)

    assert result.output_text.strip()
    assert result.latency_ms > 0
    if result.usage is not None and result.usage.input_tokens is not None:
        assert 0 < result.usage.input_tokens < 200
    if result.actual_cost_usd is not None:
        assert result.actual_cost_usd <= ceiling
    store = SQLiteObservationStore(tmp_path / "live.sqlite3")
    store.record_observation(result.to_stored_observation())
    assert len(store.query_observations(model_id=model)) == 1


def _worst_case_cost_usd(model: str, max_tokens: int) -> Optional[Decimal]:
    """Upper-bound the request cost from LiteLLM's price table, or None when the model is unpriced."""
    prices = litellm.model_cost.get(model)
    if not prices or "input_cost_per_token" not in prices or "output_cost_per_token" not in prices:
        return None
    return (
        Decimal(str(prices["input_cost_per_token"])) * 50 + Decimal(str(prices["output_cost_per_token"])) * max_tokens
    )


@pytest.mark.unit
async def test_live_execution_skips_when_price_is_unavailable(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """[Unit] live cost guard: unknown pricing skips before the backend can send a billable request.

    Scenario: Enable the live test with a model whose preflight cost cannot be determined.
    Boundaries: LiteLLM pricing and backend execution are monkeypatched; no network or credentials.
    On failure, first check: the live test's preflight skip for unknown pricing.
    """
    monkeypatch.setenv("MODEL_ANALYTICS_LIVE_LLM", "1")
    monkeypatch.setenv("MODEL_ANALYTICS_LIVE_MODEL", "unpriced-model")
    monkeypatch.setattr(litellm, "model_cost", {})

    async def unexpected_execution(self: LiteLLMBackend, request: ExecutionRequest):
        """Fail if the safety guard allows execution."""
        del self, request
        raise AssertionError("execution must not start without a known cost")

    monkeypatch.setattr(LiteLLMBackend, "execute", unexpected_execution)
    with pytest.raises(pytest.skip.Exception, match="Cannot determine worst-case cost"):
        await test_live_execution_records_observation_in_temp_db(tmp_path)
