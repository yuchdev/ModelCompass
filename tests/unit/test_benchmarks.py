from __future__ import annotations

import pytest

from model_compass.benchmarks import (
    BenchmarkCase,
    BenchmarkDataset,
    EvaluatorType,
    evaluate_benchmark,
)
from model_compass.exceptions import BenchmarkError


@pytest.mark.unit
@pytest.mark.parametrize(
    ("evaluator", "expected", "actual", "passed"),
    [
        (EvaluatorType.EXACT, "answer", "answer", True),
        (EvaluatorType.EXACT, "answer", "Answer", False),
        (EvaluatorType.REGEX, r"answer-\d+", "answer-42", True),
        (EvaluatorType.REGEX, r"answer-\d+", "answer-x", False),
        (EvaluatorType.JSON, '{"a": 1}', '{"a":1}', True),
        (EvaluatorType.JSON, '{"a": 1}', "not-json", False),
    ],
)
def test_benchmark_evaluators_are_deterministic(
    evaluator: EvaluatorType, expected: str, actual: str, passed: bool
) -> None:
    dataset = BenchmarkDataset(
        name="fixture",
        task="classification",
        evaluator=evaluator,
        cases=(BenchmarkCase(case_id="one", input_text="question", expected_output=expected),),
    )
    report = evaluate_benchmark(dataset, {"one": actual}, model_id="test:model")

    assert report.sample_size == 1
    assert report.quality_score == (1 if passed else 0)
    assert report.cases[0].passed is passed


@pytest.mark.unit
def test_benchmark_missing_and_unknown_outputs_are_explicit() -> None:
    dataset = BenchmarkDataset(
        name="fixture",
        task="qa",
        evaluator=EvaluatorType.EXACT,
        cases=(
            BenchmarkCase(case_id="one", input_text="q1", expected_output="a1"),
            BenchmarkCase(case_id="two", input_text="q2", expected_output="a2"),
        ),
    )
    report = evaluate_benchmark(dataset, {"one": "a1"}, model_id="test:model")
    assert report.quality_score == 0.5
    assert report.cases[1].passed is False

    with pytest.raises(ValueError, match="unknown case ids"):
        evaluate_benchmark(dataset, {"unexpected": "answer"}, model_id="test:model")
    with pytest.raises(ValueError, match="at least one"):
        evaluate_benchmark(dataset.model_copy(update={"cases": ()}), {}, model_id="test:model")


@pytest.mark.unit
def test_benchmark_rejects_duplicate_case_ids() -> None:
    dataset = BenchmarkDataset(
        name="fixture",
        task="qa",
        evaluator=EvaluatorType.EXACT,
        cases=(
            BenchmarkCase(case_id="one", input_text="q1", expected_output="a1"),
            BenchmarkCase(case_id="one", input_text="q2", expected_output="a2"),
        ),
    )
    with pytest.raises(BenchmarkError, match="duplicate case ids: one"):
        evaluate_benchmark(dataset, {"one": "a1"}, model_id="test:model")


@pytest.mark.unit
def test_benchmark_invalid_regex_raises_benchmark_error() -> None:
    dataset = BenchmarkDataset(
        name="fixture",
        task="qa",
        evaluator=EvaluatorType.REGEX,
        cases=(BenchmarkCase(case_id="one", input_text="q", expected_output="("),),
    )
    with pytest.raises(BenchmarkError, match="invalid regex"):
        evaluate_benchmark(dataset, {"one": "a"}, model_id="test:model")
