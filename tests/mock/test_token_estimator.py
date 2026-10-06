from __future__ import annotations

from typing import Any

import litellm
import pytest

from model_compass.metrics import LiteLLMTokenEstimator


@pytest.mark.mock
def test_litellm_estimator_returns_model_specific_count(monkeypatch: pytest.MonkeyPatch):
    """[Local] exact count: the estimator returns LiteLLM's model-specific token count.

    Scenario: Patches litellm.token_counter to return a fixed count and estimates a prompt.
    Boundaries: Real LiteLLMTokenEstimator; litellm.token_counter is monkeypatched.
    On failure, first check: the estimator forwarding args and reporting an exact litellm source.
    """

    def token_counter(**kwargs: Any) -> int:
        """Assert the forwarded arguments and return a fixed token count."""
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
        pytest.param(lambda **kwargs: (_ for _ in ()).throw(ValueError("unsupported")), id="unsupported"),
        pytest.param(lambda **kwargs: (_ for _ in ()).throw(LookupError("failed")), id="exception"),
        pytest.param(lambda **kwargs: "not-a-count", id="malformed"),
    ],
)
def test_litellm_fallback_discloses_approximation(monkeypatch: pytest.MonkeyPatch, token_counter: Any):
    """[Local] fallback disclosure: counting failures fall back to chars-per-token with a note.

    Scenario: Patches token_counter to raise or return garbage and estimates a known-length prompt.
    Boundaries: Real LiteLLMTokenEstimator; litellm.token_counter is monkeypatched per parameter set.
    On failure, first check: the fallback source label and the approximation note being disclosed.
    """
    monkeypatch.setattr(litellm, "token_counter", token_counter)
    result = LiteLLMTokenEstimator().estimate(model="unsupported", prompt="abcdefgh")
    assert result.input_tokens == 2
    assert result.source == "fallback_chars_per_token"
    assert result.exact is False
    assert any("LiteLLM token counting unavailable" in note for note in result.notes)


@pytest.mark.mock
def test_explicit_token_count_skips_litellm(monkeypatch: pytest.MonkeyPatch):
    """[Local] explicit count bypass: an explicit input token count skips litellm entirely.

    Scenario: Patches token_counter to fail if called and estimates with explicit_input_tokens set.
    Boundaries: Real LiteLLMTokenEstimator; litellm.token_counter is monkeypatched to fail-on-call.
    On failure, first check: the explicit-count shortcut avoiding any retokenization.
    """

    def token_counter(**kwargs: Any) -> int:
        """Fail if called, since explicit token counts must not be retokenized."""
        pytest.fail("explicit input token counts must not be retokenized")

    monkeypatch.setattr(litellm, "token_counter", token_counter)
    result = LiteLLMTokenEstimator().estimate(model="model", prompt="ignore", explicit_input_tokens=99)
    assert result.input_tokens == 99
    assert result.source == "explicit"
