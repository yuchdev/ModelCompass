"""Reusable synthetic workload scenarios for comparisons and examples."""

from typing import Optional

from pydantic import BaseModel, ConfigDict

from model_compass.domain import RequestProfile


class WorkloadScenario(BaseModel):
    """Named synthetic request assumptions, not an application claim."""

    model_config = ConfigDict(frozen=True)

    name: str
    profile: RequestProfile
    description: str


_SCENARIOS: dict[str, tuple[int, int, bool]] = {
    "short-chat": (128, 128, False),
    "balanced": (2048, 512, False),
    "input-heavy": (8192, 256, False),
    "long-context": (32768, 1024, False),
    "output-heavy": (1024, 4096, False),
    "agent-step": (2048, 1024, True),
}


def workload_scenario(name: str) -> WorkloadScenario:
    """Return a built-in scenario by name."""
    try:
        input_tokens, output_tokens, requires_tools = _SCENARIOS[name]
    except KeyError as exc:
        raise ValueError(f"unknown workload scenario: {name}") from exc
    return WorkloadScenario(
        name=name,
        profile=RequestProfile(
            task=name,
            input_modalities=frozenset({"text"}),
            explicit_input_tokens=input_tokens,
            expected_output_tokens=output_tokens,
            minimum_context=input_tokens + output_tokens,
            requires_tools=requires_tools,
        ),
        description=(
            f"Synthetic {name} workload with {input_tokens} input and {output_tokens} output "
            "tokens; these values are comparison assumptions, not measured application usage."
        ),
    )


def custom_workload_scenario(
    name: str,
    *,
    input_tokens: int,
    output_tokens: int,
    requires_tools: bool = False,
    minimum_context: Optional[int] = None,
) -> WorkloadScenario:
    """Create a user-defined synthetic scenario."""
    profile = RequestProfile(
        task=name,
        input_modalities=frozenset({"text"}),
        explicit_input_tokens=input_tokens,
        expected_output_tokens=output_tokens,
        minimum_context=(minimum_context if minimum_context is not None else input_tokens + output_tokens),
        requires_tools=requires_tools,
    )
    return WorkloadScenario(
        name=name,
        profile=profile,
        description=f"User-defined synthetic scenario: {input_tokens} input and {output_tokens} output tokens.",
    )
