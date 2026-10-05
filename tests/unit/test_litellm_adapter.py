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
async def test_litellm_adapter_missing_dependency(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delitem(sys.modules, "litellm", raising=False)

    original_import = __import__("builtins").__import__

    def _import(name: str, *args: object, **kwargs: object) -> object:
        if name == "litellm":
            raise ImportError("missing")
        return original_import(name, *args, **kwargs)

    monkeypatch.setattr(__import__("builtins"), "__import__", _import)

    adapter = LiteLLMCatalogAdapter()
    with pytest.raises(DependencyError):
        await adapter.refresh()


@pytest.mark.unit
@pytest.mark.asyncio
async def test_litellm_adapter_normalization(monkeypatch: pytest.MonkeyPatch) -> None:
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
