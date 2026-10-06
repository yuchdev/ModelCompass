"""Optional, opt-in LLM-judge evaluator. Never enabled implicitly by a dataset alone."""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.benchmarks.dataset import BenchmarkCase
from model_compass.benchmarks.evaluators import EvaluationContext, EvaluationResult
from model_compass.exceptions import BenchmarkError
from model_compass.execution.backend import CompletionRequest, ExecutionBackend, ExecutionError

#: `{task}`, `{input}`, `{expected}`, and `{response}` are substituted per case.
DEFAULT_JUDGE_PROMPT_TEMPLATE = (
    "You are grading a response for the task {task!r}.\n"
    "Input: {input}\n"
    "Expected (if any): {expected}\n"
    "Candidate response: {response}\n\n"
    'Reply with only a JSON object: {{"score": <0 to 1>, "explanation": "<short reason>"}}.'
)


class JudgeEvaluationError(BenchmarkError):
    """Raised when the judge cannot produce a trustworthy score; never a fabricated 0."""


class JudgeConfig(BaseModel):
    """Explicit configuration for an LLM-judge evaluator; nothing here is inferred."""

    model_config = ConfigDict(frozen=True)

    judge_model_id: str = Field(min_length=1)
    prompt_version: str = Field(min_length=1)
    prompt_template: str = DEFAULT_JUDGE_PROMPT_TEMPLATE
    temperature: Decimal = Decimal(0)
    extra_parameters: dict[str, Any] = Field(default_factory=dict)

    @field_validator("temperature")
    @classmethod
    def _non_negative_temperature(cls, value: Decimal) -> Decimal:
        """Reject a non-finite or negative temperature."""
        if not value.is_finite() or value < 0:
            raise ValueError("temperature must be finite and non-negative")
        return value


class LLMJudgeEvaluator:
    """Scores responses using a separately configured judge model, never the candidate."""

    evaluator_id = "llm_judge"

    def __init__(self, *, backend: ExecutionBackend, config: JudgeConfig):
        """Store the execution backend used to call the judge model and its configuration."""
        self._backend = backend
        self.config = config
        self.evaluator_version = config.prompt_version

    async def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Call the judge model and parse its structured verdict.

        Raises `JudgeEvaluationError` on any failure (backend error, malformed
        output, out-of-range score) rather than returning a fabricated score, so
        the caller can record the case as failed instead of silently scoring it.
        """
        if context.model_id == self.config.judge_model_id:
            raise JudgeEvaluationError(
                f"the configured judge ({self.config.judge_model_id}) must not evaluate itself as the candidate"
            )
        prompt = self.config.prompt_template.format(
            task=case.task,
            input=case.input_text if case.input_text is not None else json.dumps(case.messages),
            expected=case.expected_output or case.expected_json or "(no reference answer provided)",
            response=response,
        )
        request = CompletionRequest(
            model_id=self.config.judge_model_id,
            task=f"llm_judge:{case.task}",
            messages=[{"role": "user", "content": prompt}],
            parameters={"temperature": float(self.config.temperature), **self.config.extra_parameters},
        )
        try:
            result = await self._backend.execute(request)
        except ExecutionError as exc:
            raise JudgeEvaluationError(f"judge backend execution failed: {exc}") from exc

        score, explanation = _parse_judge_output(result.output_text)
        return EvaluationResult(
            score=score,
            passed=None,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.config.prompt_version,
            explanation=explanation,
            details={
                "judge_model_id": self.config.judge_model_id,
                "judge_prompt_version": self.config.prompt_version,
                "judge_cost_usd": str(result.actual_cost_usd) if result.actual_cost_usd is not None else None,
                "judge_latency_ms": result.latency_ms,
            },
        )


def _parse_judge_output(output_text: str) -> tuple[Decimal, str]:
    """Parse the judge's structured JSON output into a bounded score and explanation."""
    try:
        parsed = json.loads(output_text)
        if not isinstance(parsed, dict):
            raise TypeError("judge output must be a JSON object")
        score = Decimal(str(parsed["score"]))
        explanation = str(parsed.get("explanation", ""))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, InvalidOperation) as exc:
        raise JudgeEvaluationError(f"judge produced malformed structured output: {exc}") from exc
    if not score.is_finite() or not Decimal("0") <= score <= Decimal("1"):
        raise JudgeEvaluationError(f"judge score out of bounds: {score}")
    return score, explanation


def judge_cost_usd(result: EvaluationResult) -> Optional[Decimal]:
    """Extract the judge's own execution cost from an evaluation result's details."""
    raw = result.details.get("judge_cost_usd")
    return Decimal(raw) if raw is not None else None
