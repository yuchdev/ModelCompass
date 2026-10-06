from __future__ import annotations

import sys
import types
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from model_compass.catalogs.litellm import LiteLLMCatalogAdapter
from model_compass.exceptions import DependencyError


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_adapter_missing_dependency(monkeypatch: pytest.MonkeyPatch):
    """[Unit] missing LiteLLM: verifies refresh raises DependencyError when LiteLLM can't be imported.

    Scenario: Set sys.modules["litellm"] = None, the documented way to force
        ModuleNotFoundError on import, then call LiteLLMCatalogAdapter.refresh.
    Boundaries: Only sys.modules is faked; the adapter's own logic runs for real.
    On failure, first check: LiteLLMCatalogAdapter.refresh's ImportError handling.
    """
    monkeypatch.setitem(sys.modules, "litellm", None)

    adapter = LiteLLMCatalogAdapter()
    with pytest.raises(DependencyError):
        await adapter.refresh()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_adapter_normalization(monkeypatch: pytest.MonkeyPatch):
    """[Unit] model normalization: verifies model_cost entries are normalized into canonical profiles.

    Scenario: Inject a fake litellm module with an openrouter-prefixed, a bare, and an
        anthropic-prefixed model_cost entry, then refresh the adapter.
    Boundaries: litellm itself is a fake module in sys.modules; normalization logic runs for real.
    On failure, first check: LiteLLMCatalogAdapter.refresh's provider/model_id normalization.
    """
    fake = types.SimpleNamespace(
        model_cost={
            "openrouter/openai/gpt-4o-mini": {
                "prompt_cost_per_token": "0.1",
                "completion_cost_per_token": "0.2",
                "max_input_tokens": 100,
            },
            "gpt-local": {
                "input_cost_per_token": "0.3",
            },
            "anthropic/claude-3-haiku": {
                "input_cost_per_token": "0.4",
            },
        }
    )
    monkeypatch.setitem(sys.modules, "litellm", fake)

    adapter = LiteLLMCatalogAdapter()
    snapshot = await adapter.refresh(now_utc=datetime(2026, 1, 1, tzinfo=UTC))

    openrouter = snapshot.models["openrouter:openai/gpt-4o-mini"]
    assert openrouter.pricing.components["prompt"].amount == Decimal("0.1")
    local = snapshot.models["litellm:gpt-local"]
    assert local.pricing.components["prompt"].amount == Decimal("0.3")
    anthropic = snapshot.models["anthropic:claude-3-haiku"]
    assert anthropic.pricing.components["prompt"].amount == Decimal("0.4")
