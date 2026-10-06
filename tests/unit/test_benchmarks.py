from __future__ import annotations

import pytest

from model_compass.benchmarks import BenchmarkCase, BenchmarkDataset, evaluate_offline
from model_compass.exceptions import BenchmarkError


@pytest.mark.unit
@pytest.mark.parametrize(
    ("evaluator", "expected_output", "actual", "passed"),
    [
        ("exact", "answer", "answer", True),
        ("exact", "answer", "Answer", False),
        ("regex", r"answer-\d+", "answer-42", True),
        ("regex", r"answer-\d+", "answer-x", False),
    ],
)
def test_offline_evaluation_scores_deterministic_evaluators(
    evaluator: str, expected_output: str, actual: str, passed: bool
):
    """[Unit] offline evaluation: exact/regex evaluators pass or fail as expected.

    Scenario: Runs a one-case single-task dataset through evaluate_offline with
        matching and non-matching outputs.
    Boundaries: Pure evaluation logic over an in-memory dataset; no I/O.
    On failure, first check: the evaluator comparison for the failing evaluator/input combination.
    """
    dataset = BenchmarkDataset(
        name="fixture",
        version="1.0.0",
        cases=(
            BenchmarkCase(
                case_id="one",
                task="classification",
                input_text="question",
                evaluator=evaluator,
                expected_output=expected_output,
            ),
        ),
    )
    report = evaluate_offline(dataset, {"one": actual}, model_id="test:model")

    assert report.sample_size == 1
    assert report.quality_score == (1 if passed else 0)
    assert report.cases[0].passed is passed


@pytest.mark.unit
def test_offline_evaluation_missing_and_unknown_outputs_are_explicit():
    """[Unit] missing/unknown outputs: missing answers fail and unknown case ids are rejected.

    Scenario: Scores a two-case dataset with one answer, then feeds unknown ids and an empty dataset.
    Boundaries: Pure evaluation logic over in-memory datasets; no I/O.
    On failure, first check: partial-score handling and the unknown-case-id and empty-dataset guards.
    """
    dataset = BenchmarkDataset(
        name="fixture",
        version="1.0.0",
        cases=(
            BenchmarkCase(case_id="one", task="qa", input_text="q1", evaluator="exact", expected_output="a1"),
            BenchmarkCase(case_id="two", task="qa", input_text="q2", evaluator="exact", expected_output="a2"),
        ),
    )
    report = evaluate_offline(dataset, {"one": "a1"}, model_id="test:model")
    assert report.quality_score == 0.5
    assert report.cases[1].passed is False

    with pytest.raises(BenchmarkError, match="unknown case ids"):
        evaluate_offline(dataset, {"unexpected": "answer"}, model_id="test:model")
    with pytest.raises(BenchmarkError, match="at least one"):
        evaluate_offline(dataset.model_copy(update={"cases": ()}), {}, model_id="test:model")


@pytest.mark.unit
def test_offline_evaluation_rejects_mixed_task_datasets():
    """[Unit] mixed-task rejection: offline evaluation requires a single-task dataset.

    Scenario: Builds a dataset with two cases spanning different tasks and evaluates it.
    Boundaries: Pure evaluation logic over an in-memory dataset; no I/O.
    On failure, first check: evaluate_offline's single-task guard.
    """
    dataset = BenchmarkDataset(
        name="fixture",
        version="1.0.0",
        cases=(
            BenchmarkCase(case_id="one", task="qa", input_text="q1", evaluator="exact", expected_output="a1"),
            BenchmarkCase(
                case_id="two", task="summarization", input_text="q2", evaluator="exact", expected_output="a2"
            ),
        ),
    )
    with pytest.raises(BenchmarkError, match="single-task dataset"):
        evaluate_offline(dataset, {"one": "a1", "two": "a2"}, model_id="test:model")


@pytest.mark.unit
def test_offline_evaluation_rejects_llm_judge_cases():
    """[Unit] judge rejection: offline evaluation refuses cases that require the LLM judge.

    Scenario: Builds a single case whose evaluator is 'llm_judge' and evaluates it offline.
    Boundaries: Pure evaluation logic; no execution backend is available in this path.
    On failure, first check: evaluate_offline's llm_judge guard.
    """
    dataset = BenchmarkDataset(
        name="fixture",
        version="1.0.0",
        cases=(
            BenchmarkCase(
                case_id="one", task="qa", input_text="q1", evaluator="llm_judge", evaluator_config={"rubric": "x"}
            ),
        ),
    )
    with pytest.raises(BenchmarkError, match="llm_judge"):
        evaluate_offline(dataset, {"one": "a1"}, model_id="test:model")


@pytest.mark.unit
def test_benchmark_dataset_rejects_duplicate_case_ids():
    """[Unit] duplicate case ids: a dataset with repeated case ids raises on construction.

    Scenario: Builds a dataset with two cases sharing an id.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: BenchmarkDataset's duplicate-case-id validator.
    """
    with pytest.raises(ValueError, match="duplicate case ids: one"):
        BenchmarkDataset(
            name="fixture",
            version="1.0.0",
            cases=(
                BenchmarkCase(case_id="one", task="qa", input_text="q1", evaluator="exact", expected_output="a1"),
                BenchmarkCase(case_id="one", task="qa", input_text="q2", evaluator="exact", expected_output="a2"),
            ),
        )


@pytest.mark.unit
def test_offline_evaluation_invalid_regex_raises_benchmark_error():
    """[Unit] invalid regex: an uncompilable regex expectation raises BenchmarkError.

    Scenario: Uses the regex evaluator with an invalid expected pattern and evaluates it.
    Boundaries: Pure evaluation logic over an in-memory dataset; no I/O.
    On failure, first check: regex compilation errors being wrapped into BenchmarkError.
    """
    dataset = BenchmarkDataset(
        name="fixture",
        version="1.0.0",
        cases=(BenchmarkCase(case_id="one", task="qa", input_text="q", evaluator="regex", expected_output="("),),
    )
    with pytest.raises(BenchmarkError, match="invalid regex"):
        evaluate_offline(dataset, {"one": "a"}, model_id="test:model")
