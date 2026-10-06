"""Token estimation with explicit provenance for exact and approximate counts."""

from __future__ import annotations

import importlib
from collections.abc import Mapping, Sequence
from typing import Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field

Message = Mapping[str, object]


class TokenEstimate(BaseModel):
    """Estimated request token usage and its provenance."""

    model_config = ConfigDict(frozen=True)

    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    source: str
    exact: bool
    notes: tuple[str, ...] = ()


class TokenEstimator(Protocol):
    """Provider-independent contract for request token estimators."""

    def estimate(
        self,
        *,
        model: str,
        prompt: Optional[str] = None,
        messages: Optional[Sequence[Message]] = None,
        explicit_input_tokens: Optional[int] = None,
        expected_output_tokens: Optional[int] = None,
    ) -> TokenEstimate:
        """Estimate token usage for a request."""


class FallbackTokenEstimator:
    """Character-based approximation for requests LiteLLM cannot tokenize."""

    def estimate(
        self,
        *,
        model: str,
        prompt: Optional[str] = None,
        messages: Optional[Sequence[Message]] = None,
        explicit_input_tokens: Optional[int] = None,
        expected_output_tokens: Optional[int] = None,
    ) -> TokenEstimate:
        """Estimate tokens from character counts, four characters per token."""
        del model
        if explicit_input_tokens is not None:
            input_tokens = explicit_input_tokens
            source = "explicit"
            exact = True
            notes = ["Input token count supplied explicitly; it was not retokenized."]
        else:
            input_tokens = (_character_count(prompt, messages) + 3) // 4
            source = "fallback_chars_per_token"
            exact = False
            notes = ["Approximation: input tokens estimated as one token per four characters."]
        output_tokens = expected_output_tokens or 0
        if expected_output_tokens is not None:
            notes.append("Output token count is the expected scenario value.")
        else:
            notes.append("Output token usage was not supplied and is assumed to be zero.")
        return TokenEstimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            source=source,
            exact=exact,
            notes=tuple(notes),
        )


class LiteLLMTokenEstimator:
    """Use LiteLLM token counting, falling back with disclosed approximation."""

    def __init__(self, fallback: Optional[TokenEstimator] = None):
        """Store the fallback estimator to use if LiteLLM token counting fails."""
        self._fallback = fallback or FallbackTokenEstimator()

    def estimate(
        self,
        *,
        model: str,
        prompt: Optional[str] = None,
        messages: Optional[Sequence[Message]] = None,
        explicit_input_tokens: Optional[int] = None,
        expected_output_tokens: Optional[int] = None,
    ) -> TokenEstimate:
        """Estimate tokens via LiteLLM, falling back on any known tokenizer failure."""
        if explicit_input_tokens is not None:
            notes = ["Input token count supplied explicitly; it was not retokenized."]
            notes.append(
                "Output token count is the expected scenario value."
                if expected_output_tokens is not None
                else "Output token usage was not supplied and is assumed to be zero."
            )
            return TokenEstimate(
                input_tokens=explicit_input_tokens,
                output_tokens=expected_output_tokens or 0,
                source="explicit",
                exact=True,
                notes=tuple(notes),
            )
        try:
            litellm = importlib.import_module("litellm")

            kwargs: dict[str, object] = {"model": model}
            if messages is not None:
                kwargs["messages"] = list(messages)
            elif prompt is not None:
                kwargs["prompt"] = prompt
            else:
                kwargs["prompt"] = ""
            count = litellm.token_counter(**kwargs)
            if isinstance(count, bool) or not isinstance(count, int) or count < 0:
                raise ValueError("LiteLLM returned a malformed token count")
        except _token_counter_failure_types() as exc:
            fallback_estimate = self._fallback.estimate(
                model=model,
                prompt=prompt,
                messages=messages,
                expected_output_tokens=expected_output_tokens,
            )
            return fallback_estimate.model_copy(
                update={
                    "notes": (
                        *fallback_estimate.notes,
                        f"LiteLLM token counting unavailable ({type(exc).__name__}); fallback used.",
                    )
                }
            )
        notes = ["Input count tokenized by LiteLLM for the requested model."]
        output_tokens = expected_output_tokens or 0
        if expected_output_tokens is not None:
            notes.append("Output token count is the expected scenario value.")
        else:
            notes.append("Output token usage was not supplied and is assumed to be zero.")
        return TokenEstimate(
            input_tokens=count,
            output_tokens=output_tokens,
            source="litellm",
            exact=True,
            notes=tuple(notes),
        )


def _token_counter_failure_types() -> tuple[type[Exception], ...]:
    """Return the known exception types LiteLLM's tokenizer path can raise."""
    litellm_exceptions = importlib.import_module("litellm.exceptions")
    return (
        *litellm_exceptions.LITELLM_EXCEPTION_TYPES,
        ValueError,
        LookupError,
        TypeError,
        ImportError,
        AttributeError,
    )


def _character_count(prompt: Optional[str], messages: Optional[Sequence[Message]]) -> int:
    """Count characters across a prompt string or message contents."""
    if prompt is not None:
        return len(prompt)
    if messages is None:
        return 0
    return sum(len(str(message.get("content", ""))) for message in messages)
