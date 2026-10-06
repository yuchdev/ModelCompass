from __future__ import annotations

from decimal import Decimal

import pytest

from model_compass.benchmarks import BenchmarkCase, JudgeConfig, LLMJudgeEvaluator
from model_compass.benchmarks.evaluators import EvaluationContext
from model_compass.benchmarks.judge import JudgeEvaluationError, judge_cost_usd
from tests.fixtures.fake_execution_backend import FakeExecutionBackend

_CASE = BenchmarkCase(case_id="c1", task="qa", input_text="what is 2+2?", evaluator="llm_judge")
_CONTEXT = EvaluationContext(model_id="candidate:model", dataset_name="fixture")


@pytest.mark.mock
@pytest.mark.asyncio
async def test_llm_judge_parses_structured_response_and_records_cost():
    """[Local] judge success: a well-formed structured judge response yields a bounded score.

    Scenario: A fake backend returns {"score": 0.9, "explanation": "..."} for the judge model.
    Boundaries: Real LLMJudgeEvaluator; the execution backend is a local fake, no network.
    On failure, first check: LLMJudgeEvaluator._parse_judge_output and cost recording in details.
    """
    backend = FakeExecutionBackend(
        {"judge:model": '{"score": 0.9, "explanation": "mostly correct"}'}, cost_usd=Decimal("0.002")
    )
    judge = LLMJudgeEvaluator(backend=backend, config=JudgeConfig(judge_model_id="judge:model", prompt_version="v1"))
    result = await judge.evaluate(_CASE, "4", _CONTEXT)

    assert result.score == Decimal("0.9")
    assert result.evaluator_id == "llm_judge"
    assert result.evaluator_version == "v1"
    assert result.explanation == "mostly correct"
    assert judge_cost_usd(result) == Decimal("0.002")
    assert backend.calls[0].model_id == "judge:model"


@pytest.mark.mock
@pytest.mark.asyncio
async def test_llm_judge_raises_on_malformed_output_without_fabricating_a_score():
    """[Local] judge malformed output: non-JSON or out-of-range judge output raises, never scores.

    Scenario: The fake backend returns non-JSON text, then JSON missing 'score', then an out-of-range score.
    Boundaries: Real LLMJudgeEvaluator; the execution backend is a local fake, no network.
    On failure, first check: LLMJudgeEvaluator raising JudgeEvaluationError instead of returning a result.
    """
    for malformed_output in ("not json at all", '{"explanation": "no score field"}', '{"score": 1.5}'):
        backend = FakeExecutionBackend({"judge:model": malformed_output})
        judge = LLMJudgeEvaluator(
            backend=backend, config=JudgeConfig(judge_model_id="judge:model", prompt_version="v1")
        )
        with pytest.raises(JudgeEvaluationError):
            await judge.evaluate(_CASE, "4", _CONTEXT)


@pytest.mark.mock
@pytest.mark.asyncio
async def test_llm_judge_raises_on_backend_execution_failure():
    """[Local] judge backend failure: an execution error from the judge call raises, not a score.

    Scenario: The fake backend is configured to fail for the judge model.
    Boundaries: Real LLMJudgeEvaluator; the execution backend is a local fake, no network.
    On failure, first check: LLMJudgeEvaluator wrapping ExecutionError into JudgeEvaluationError.
    """
    backend = FakeExecutionBackend(fail_models=frozenset({"judge:model"}))
    judge = LLMJudgeEvaluator(backend=backend, config=JudgeConfig(judge_model_id="judge:model", prompt_version="v1"))
    with pytest.raises(JudgeEvaluationError, match="judge backend execution failed"):
        await judge.evaluate(_CASE, "4", _CONTEXT)


@pytest.mark.mock
@pytest.mark.asyncio
async def test_llm_judge_refuses_to_evaluate_its_own_candidate():
    """[Local] non-self-judging: the judge refuses when the candidate model is the judge itself.

    Scenario: Builds an evaluation context whose model_id equals the configured judge_model_id.
    Boundaries: Real LLMJudgeEvaluator; no backend call should occur.
    On failure, first check: LLMJudgeEvaluator.evaluate's self-judging guard, checked before any backend call.
    """
    backend = FakeExecutionBackend({"judge:model": '{"score": 1.0}'})
    judge = LLMJudgeEvaluator(backend=backend, config=JudgeConfig(judge_model_id="judge:model", prompt_version="v1"))
    self_context = EvaluationContext(model_id="judge:model", dataset_name="fixture")
    with pytest.raises(JudgeEvaluationError, match="must not evaluate itself"):
        await judge.evaluate(_CASE, "4", self_context)
    assert backend.calls == []
