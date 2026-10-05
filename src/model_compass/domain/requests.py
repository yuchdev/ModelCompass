"""Validated request requirements and conservative request inference."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.domain.models import parse_decimal


class RequestProfile(BaseModel):
    """Explicit and inferred requirements for one model request."""

    model_config = ConfigDict(frozen=True)

    task: str | None = None
    input_modalities: frozenset[str] = frozenset()
    output_modalities: frozenset[str] = frozenset()
    explicit_input_tokens: int | None = Field(default=None, ge=0)
    expected_output_tokens: int | None = Field(default=None, ge=0)
    minimum_context: int | None = Field(default=None, ge=0)
    requires_tools: bool | None = None
    requires_structured_output: bool | None = None
    requires_reasoning: bool | None = None
    requires_streaming: bool | None = None
    max_cost_usd: Decimal | None = Field(default=None, ge=0)
    min_quality: Decimal | None = Field(default=None, ge=0, le=1)
    max_latency_ms: int | None = Field(default=None, ge=0)
    min_reliability: Decimal | None = Field(default=None, ge=0, le=1)
    metadata: Mapping[str, object] = Field(default_factory=dict)

    @field_validator("input_modalities", "output_modalities", mode="before")
    @classmethod
    def _normalize_modalities(cls, value: object) -> frozenset[str]:
        if isinstance(value, str):
            values: list[object] = [value]
        elif isinstance(value, (Sequence, set, frozenset)):
            values = list(value)
        else:
            raise TypeError("modalities must be a sequence of strings")
        if any(not isinstance(item, str) or not item.strip() for item in values):
            raise ValueError("modalities must contain non-empty strings only")
        return frozenset(item.strip().lower() for item in values if isinstance(item, str))

    @field_validator("max_cost_usd", "min_quality", "min_reliability", mode="before")
    @classmethod
    def _parse_decimal_values(cls, value: object) -> Decimal | None:
        return None if value is None else parse_decimal(value)

    @classmethod
    def from_request(
        cls,
        *,
        prompt: str | None = None,
        messages: Sequence[Mapping[str, object]] | None = None,
        tools: Sequence[Mapping[str, object]] | None = None,
        response_schema: Mapping[str, object] | None = None,
        **requirements: Any,
    ) -> RequestProfile:
        """Build a profile, preferring every explicitly supplied requirement."""
        inferred: dict[str, object] = {}
        has_text, has_image = _infer_input_modalities(prompt, messages)
        inferred_modalities: set[str] = set()
        if has_text:
            inferred_modalities.add("text")
        if has_image:
            inferred_modalities.add("image")
        if inferred_modalities:
            inferred["input_modalities"] = frozenset(inferred_modalities)
        if tools:
            inferred["requires_tools"] = True
        if response_schema is not None:
            inferred["requires_structured_output"] = True

        expected_output = requirements.get("expected_output_tokens")
        explicit_input = requirements.get("explicit_input_tokens")
        content_size = _request_character_count(prompt, messages)
        if "minimum_context" not in requirements and content_size:
            input_size = (
                explicit_input if isinstance(explicit_input, int) else (content_size + 3) // 4
            )
            reserve = expected_output if isinstance(expected_output, int) else 0
            inferred["minimum_context"] = input_size + reserve
            context_assumptions = [
                "Context input size uses explicit_input_tokens."
                if isinstance(explicit_input, int)
                else "Context input size is approximated as one token per four request characters."
            ]
            context_assumptions.append(
                "expected_output_tokens is reserved."
                if isinstance(expected_output, int)
                else "No output-token reserve was added because expected_output_tokens was omitted."
            )
            caller_metadata = requirements.get("metadata", {})
            if isinstance(caller_metadata, Mapping):
                inferred["metadata"] = {
                    **caller_metadata,
                    "inference_assumptions": tuple(context_assumptions),
                }
            else:
                inferred["metadata"] = {"inference_assumptions": tuple(context_assumptions)}

        values = {**inferred, **requirements}
        return cls(**values)


def build_request_profile(
    *,
    prompt: str | None = None,
    messages: Sequence[Mapping[str, object]] | None = None,
    tools: Sequence[Mapping[str, object]] | None = None,
    response_schema: Mapping[str, object] | None = None,
    **requirements: Any,
) -> RequestProfile:
    """Public factory for explicit requirements and conservative inference."""
    return RequestProfile.from_request(
        prompt=prompt,
        messages=messages,
        tools=tools,
        response_schema=response_schema,
        **requirements,
    )


def _infer_input_modalities(
    prompt: str | None, messages: Sequence[Mapping[str, object]] | None
) -> tuple[bool, bool]:
    has_text = bool(prompt)
    has_image = False
    for message in messages or ():
        content = message.get("content")
        if isinstance(content, str):
            has_text = has_text or bool(content)
        elif isinstance(content, Sequence) and not isinstance(content, (str, bytes)):
            for part in content:
                if not isinstance(part, Mapping):
                    continue
                part_type = str(part.get("type", "")).lower()
                if part_type in {"image", "image_url", "input_image"}:
                    has_image = True
                elif part_type in {"text", "input_text"} and part.get("text"):
                    has_text = True
    return has_text, has_image


def _request_character_count(
    prompt: str | None, messages: Sequence[Mapping[str, object]] | None
) -> int:
    if prompt is not None:
        return len(prompt)
    if not messages:
        return 0
    return len(json.dumps(messages, sort_keys=True, default=str))
