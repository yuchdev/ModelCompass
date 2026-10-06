from __future__ import annotations

from decimal import Decimal

import pytest

from model_compass.benchmarks import (
    BenchmarkCase,
    ScoredCase,
    bootstrap_confidence_interval,
    summarize_quality,
)
from model_compass.domain import BenchmarkResult
from model_compass.exceptions import BenchmarkError


def _scored(
    *,
    model_id: str = "test:model",
    case_id: str = "c1",
    task: str = "qa",
    tags: tuple[str, ...] = (),
    score: Decimal = Decimal("1"),
    passed: bool = True,
    dataset_name: str = "fixture",
) -> ScoredCase:
    """Build one scored case pairing a minimal BenchmarkCase and matching BenchmarkResult."""
    case = BenchmarkCase(case_id=case_id, task=task, tags=tags, input_text="q", evaluator="exact", expected_output="a")
    result = BenchmarkResult(
        run_id="run-1", case_id=case_id, model_id=model_id, score=score, metadata={"passed": passed}
    )
    return ScoredCase(case=case, result=result, dataset_name=dataset_name)


@pytest.mark.unit
def test_summarize_quality_groups_by_task():
    """[Unit] per-task aggregation: scores are grouped by model and task only.

    Scenario: Summarizes scored cases spanning two tasks for one model.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's group_by='task' key construction.
    """
    rows = [
        _scored(case_id="1", task="qa", score=Decimal("1")),
        _scored(case_id="2", task="qa", score=Decimal("0")),
        _scored(case_id="3", task="summarization", score=Decimal("1")),
    ]
    summaries = {s.group_key: s for s in summarize_quality(rows, group_by="task")}
    assert summaries["qa"].mean_score == Decimal("0.5")
    assert summaries["qa"].sample_count == 2
    assert summaries["summarization"].mean_score == Decimal("1")


@pytest.mark.unit
def test_summarize_quality_groups_by_dataset_and_tag():
    """[Unit] per-dataset and per-tag aggregation: cases group by dataset name or tag membership.

    Scenario: Summarizes scored cases from two datasets, one case carrying two tags.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's dataset and multi-tag grouping.
    """
    rows = [
        _scored(case_id="1", tags=("smoke", "fast"), score=Decimal("1"), dataset_name="alpha"),
        _scored(case_id="2", tags=("fast",), score=Decimal("0"), dataset_name="beta"),
    ]
    by_dataset = {s.group_key: s for s in summarize_quality(rows, group_by="dataset")}
    assert by_dataset["alpha"].sample_count == 1
    assert by_dataset["beta"].sample_count == 1

    by_tag = {s.group_key: s for s in summarize_quality(rows, group_by="tag")}
    assert by_tag["smoke"].sample_count == 1
    assert by_tag["fast"].sample_count == 2
    assert by_tag["fast"].mean_score == Decimal("0.5")


@pytest.mark.unit
def test_summarize_quality_pass_rate_reflects_recorded_verdicts():
    """[Unit] pass rate: reports the fraction of cases with a recorded boolean pass verdict.

    Scenario: Summarizes cases where some pass and some fail.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's pass_rate computation from result metadata.
    """
    rows = [_scored(case_id="1", passed=True), _scored(case_id="2", passed=False), _scored(case_id="3", passed=True)]
    summary = summarize_quality(rows, group_by="task")[0]
    assert summary.pass_rate == Decimal(2) / Decimal(3)


@pytest.mark.unit
def test_summarize_quality_overall_requires_explicit_weights():
    """[Unit] overall weighting requirement: group_by='overall' without weights raises.

    Scenario: Calls summarize_quality with group_by='overall' and no weights, then with weights
        missing one task present in the data.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's explicit-weighting guard for 'overall'.
    """
    rows = [_scored(case_id="1", task="qa"), _scored(case_id="2", task="summarization")]
    with pytest.raises(BenchmarkError, match="explicit per-task weights"):
        summarize_quality(rows, group_by="overall")
    with pytest.raises(BenchmarkError, match="missing explicit weights"):
        summarize_quality(rows, group_by="overall", weights={"qa": Decimal(1)})


@pytest.mark.unit
def test_summarize_quality_overall_uses_explicit_weights():
    """[Unit] overall weighting: the weighted mean reflects caller-supplied per-task weights.

    Scenario: Summarizes two tasks with unequal weights and checks the weighted combination.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's weighted-mean arithmetic.
    """
    rows = [
        _scored(case_id="1", task="qa", score=Decimal("1")),
        _scored(case_id="2", task="summarization", score=Decimal("0")),
    ]
    summary = summarize_quality(rows, group_by="overall", weights={"qa": Decimal(3), "summarization": Decimal(1)})[0]
    assert summary.mean_score == Decimal("0.75")
    assert summary.group_kind == "overall"
    assert summary.group_key is None


@pytest.mark.unit
def test_summarize_quality_ignores_unscored_cases():
    """[Unit] unscored cases: a result with score=None is excluded from sample_count and means.

    Scenario: Includes a scored case alongside a failed (score=None) case for the same group.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's score-is-not-None filter.
    """
    scored = _scored(case_id="1", score=Decimal("1"))
    failed = BenchmarkResult(run_id="run-1", case_id="2", model_id="test:model", score=None)
    case = BenchmarkCase(case_id="2", task="qa", input_text="q", evaluator="exact", expected_output="a")
    rows = [scored, ScoredCase(case=case, result=failed, dataset_name="fixture")]
    summary = summarize_quality(rows, group_by="task")[0]
    assert summary.sample_count == 1
    assert summary.mean_score == Decimal("1")


@pytest.mark.unit
def test_bootstrap_confidence_interval_is_deterministic_under_seed():
    """[Unit] CI determinism: the same scores and seed always produce the same interval.

    Scenario: Computes the bootstrap CI twice with the same seed and once with a different seed.
    Boundaries: Pure stdlib-random logic over an in-memory score list; no I/O.
    On failure, first check: bootstrap_confidence_interval's seeded random.Random usage.
    """
    scores = [Decimal(value) for value in ("0.2", "0.4", "0.6", "0.8", "1.0", "0.0", "0.5", "0.9")]
    first = bootstrap_confidence_interval(scores, seed=7, iterations=500)
    second = bootstrap_confidence_interval(scores, seed=7, iterations=500)
    different_seed = bootstrap_confidence_interval(scores, seed=8, iterations=500)

    assert first == second
    assert first.lower <= first.upper
    assert different_seed != first


@pytest.mark.unit
def test_bootstrap_confidence_interval_requires_at_least_two_scores():
    """[Unit] CI minimum sample size: a single score cannot support a bootstrap interval.

    Scenario: Calls bootstrap_confidence_interval with exactly one score.
    Boundaries: Pure stdlib-random logic; no I/O.
    On failure, first check: bootstrap_confidence_interval's minimum-length guard.
    """
    with pytest.raises(BenchmarkError, match="at least two scores"):
        bootstrap_confidence_interval([Decimal("0.5")], seed=1)


@pytest.mark.unit
def test_summarize_quality_attaches_confidence_interval_for_multi_sample_groups():
    """[Unit] CI attachment: a group's summary carries a confidence interval once it has 2+ samples.

    Scenario: Summarizes a one-sample group and a three-sample group for the same task.
    Boundaries: Pure aggregation logic over in-memory scored cases; no I/O.
    On failure, first check: summarize_quality's confidence_interval attachment threshold.
    """
    single = summarize_quality([_scored(case_id="1")], group_by="task")[0]
    assert single.confidence_interval is None

    multi = summarize_quality(
        [_scored(case_id="1", score=Decimal("1")), _scored(case_id="2", score=Decimal("0"))],
        group_by="task",
        seed=3,
    )[0]
    assert multi.confidence_interval is not None
    assert multi.confidence_interval.seed == 3
