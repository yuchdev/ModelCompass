from __future__ import annotations

from typing import Any

import litellm
import pytest

from model_compass.metrics import LiteLLMTokenEstimator


@pytest.mark.mock
def test_litellm_estimator_returns_model_specific_count(monkeypatch: pytest.MonkeyPatch) -> None:
    def token_counter(**kwargs: Any) -> int:
        assert kwargs == {"model": "provider/model", "prompt": "hello"}
        return 17

    monkeypatch.setattr(litellm, "token_counter", token_counter)
    result = LiteLLMTokenEstimator().estimate(model="provider/model", prompt="hello")
    assert result.input_tokens == 17
    assert result.source == "litellm"
    assert result.exact is True


@pytest.mark.mock
@pytest.mark.parametrize(
    "token_counter",
    [
        pytest.param(
            lambda **kwargs: (_ for _ in ()).throw(ValueError("unsupported")), id="unsupported"
        ),
        pytest.param(
            lambda **kwargs: (_ for _ in ()).throw(RuntimeError("failed")), id="exception"
        ),
        pytest.param(lambda **kwargs: "not-a-count", id="malformed"),
    ],
)
def test_litellm_fallback_discloses_approximation(
    monkeypatch: pytest.MonkeyPatch, token_counter: Any
) -> None:
    monkeypatch.setattr(litellm, "token_counter", token_counter)
    result = LiteLLMTokenEstimator().estimate(model="unsupported", prompt="abcdefgh")
    assert result.input_tokens == 2
    assert result.source == "fallback_chars_per_token"
    assert result.exact is False
    assert any("LiteLLM token counting unavailable" in note for note in result.notes)


@pytest.mark.mock
def test_explicit_token_count_skips_litellm(monkeypatch: pytest.MonkeyPatch) -> None:
    def token_counter(**kwargs: Any) -> int:
        pytest.fail("explicit input token counts must not be retokenized")

    monkeypatch.setattr(litellm, "token_counter", token_counter)
    result = LiteLLMTokenEstimator().estimate(
        model="model", prompt="ignore", explicit_input_tokens=99
    )
    assert result.input_tokens == 99
    assert result.source == "explicit"
