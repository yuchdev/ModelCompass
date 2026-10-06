from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from pydantic import ValidationError

from model_compass.benchmarks import (
    KNOWN_EVALUATOR_IDS,
    BenchmarkCase,
    BenchmarkDataset,
    dump_dataset_jsonl,
    load_dataset_jsonl,
)
from model_compass.exceptions import BenchmarkError

_REPO_ROOT = Path(__file__).resolve().parents[2]


def _case(**overrides: object) -> BenchmarkCase:
    """Build a minimal valid exact-match case, overriding selected fields."""
    defaults: dict[str, object] = {
        "case_id": "one",
        "task": "qa",
        "input_text": "question",
        "evaluator": "exact",
        "expected_output": "answer",
    }
    defaults.update(overrides)
    return BenchmarkCase.model_validate(defaults)


@pytest.mark.unit
def test_case_requires_exactly_one_of_messages_or_input_text():
    """[Unit] input exclusivity: a case must set exactly one of messages or input_text.

    Scenario: Constructs cases with neither, both, and exactly one of messages/input_text set.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: BenchmarkCase's input-exclusivity validator.
    """
    with pytest.raises(ValidationError, match="exactly one of messages or input_text"):
        _case(input_text=None)
    with pytest.raises(ValidationError, match="exactly one of messages or input_text"):
        _case(messages=({"role": "user", "content": "hi"},))
    assert _case().input_text == "question"
    assert _case(input_text=None, messages=({"role": "user", "content": "hi"},)).messages is not None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"evaluator": "exact", "expected_output": None}, "requires expected_output"),
        ({"evaluator": "numeric_tolerance", "expected_output": "1", "numeric_tolerance": None}, "numeric_tolerance"),
        ({"evaluator": "contains_terms", "required_terms": ()}, "required_terms"),
        ({"evaluator": "json_schema", "expected_output": None, "evaluator_config": {}}, "evaluator_config"),
    ],
)
def test_case_requires_expectation_matching_its_evaluator(overrides: dict[str, object], match: str):
    """[Unit] expectation shape: each evaluator rejects a case missing its required field.

    Scenario: Builds a case for each known evaluator with its required expectation field cleared.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: BenchmarkCase's per-evaluator expectation validator.
    """
    with pytest.raises(ValidationError, match=match):
        _case(**overrides)


@pytest.mark.unit
def test_case_accepts_custom_evaluator_id_without_shape_checks():
    """[Unit] custom evaluator: an unrecognized evaluator id is not forced into a known shape.

    Scenario: Builds a case with a made-up evaluator id and only evaluator_config set.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: BenchmarkCase skipping shape validation for unknown evaluator ids.
    """
    case = _case(evaluator="my_custom_rubric", expected_output=None, evaluator_config={"rubric": "concise"})
    assert case.evaluator == "my_custom_rubric"


@pytest.mark.unit
def test_dataset_rejects_empty_and_duplicate_cases():
    """[Unit] dataset validation: an empty case list and duplicate case ids are both rejected.

    Scenario: Constructs a dataset with zero cases, then one with two cases sharing an id.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: BenchmarkDataset's min-length and duplicate-id validators.
    """
    with pytest.raises(ValidationError):
        BenchmarkDataset(name="d", version="1.0.0", cases=())
    with pytest.raises(ValidationError, match="duplicate case ids: one"):
        BenchmarkDataset(name="d", version="1.0.0", cases=(_case(case_id="one"), _case(case_id="one")))


@pytest.mark.unit
def test_content_hash_is_stable_order_independent_and_sensitive_to_content():
    """[Unit] content hashing: the hash ignores case order but changes when content changes.

    Scenario: Hashes a dataset, a reordered copy, and a copy with one case's content changed.
    Boundaries: Pure hashing logic over in-memory datasets; no I/O.
    On failure, first check: BenchmarkDataset.content_hash's canonicalization and ordering.
    """
    case_a = _case(case_id="a")
    case_b = _case(case_id="b", expected_output="other")
    original = BenchmarkDataset(name="d", version="1.0.0", cases=(case_a, case_b))
    reordered = BenchmarkDataset(name="d", version="1.0.0", cases=(case_b, case_a))
    changed = BenchmarkDataset(name="d", version="1.0.0", cases=(case_a, _case(case_id="b", expected_output="diff")))

    assert original.content_hash == reordered.content_hash
    assert original.content_hash != changed.content_hash
    assert len(original.content_hash) == 64  # sha256 hex digest


@pytest.mark.unit
def test_dataset_identity_is_independent_of_name_and_version_changes_to_content_hash():
    """[Unit] dataset identity: identity bundles name, version, and content hash together.

    Scenario: Builds a dataset and reads its identity property.
    Boundaries: Pure in-memory logic; no I/O.
    On failure, first check: BenchmarkDataset.identity's field assembly.
    """
    dataset = BenchmarkDataset(name="my-dataset", version="2.1.0", cases=(_case(),))
    identity = dataset.identity
    assert identity.name == "my-dataset"
    assert identity.version == "2.1.0"
    assert identity.content_hash == dataset.content_hash


@pytest.mark.unit
def test_jsonl_round_trip_preserves_dataset_and_content_hash():
    """[Unit] JSONL round-trip: dump then load reproduces an identical dataset and hash.

    Scenario: Dumps a two-case dataset to JSONL text, reloads it, and compares both.
    Boundaries: Pure in-memory JSONL serialization; no filesystem I/O.
    On failure, first check: dump_dataset_jsonl/load_dataset_jsonl field round-tripping.
    """
    original = BenchmarkDataset(
        name="roundtrip",
        version="1.0.0",
        description="a tiny fixture",
        cases=(
            _case(case_id="one", tags=("smoke",), metadata={"note": "first"}),
            _case(
                case_id="two", evaluator="numeric_tolerance", expected_output="3.14", numeric_tolerance=Decimal("0.01")
            ),
        ),
    )
    text = dump_dataset_jsonl(original)
    reloaded = load_dataset_jsonl(text)

    assert reloaded == original
    assert reloaded.content_hash == original.content_hash


@pytest.mark.unit
def test_load_dataset_jsonl_requires_name_and_version_from_somewhere():
    """[Unit] identity requirement: loading without a header or explicit name/version raises.

    Scenario: Parses a JSONL blob containing only a case record and no dataset header.
    Boundaries: Pure parsing logic over an in-memory string; no filesystem I/O.
    On failure, first check: load_dataset_jsonl's header-or-explicit-identity requirement.
    """
    case_line = (
        '{"record_type":"case","case_id":"one","task":"qa","input_text":"q","evaluator":"exact","expected_output":"a"}'
    )
    with pytest.raises(BenchmarkError, match="name and version"):
        load_dataset_jsonl(case_line)
    dataset = load_dataset_jsonl(case_line, name="given", version="0.1.0")
    assert dataset.name == "given"
    assert dataset.version == "0.1.0"


@pytest.mark.unit
def test_load_dataset_jsonl_rejects_malformed_lines():
    """[Unit] malformed JSONL: an invalid record raises BenchmarkError naming its line number.

    Scenario: Parses a blob with one valid header line and one unparseable line.
    Boundaries: Pure parsing logic over an in-memory string; no filesystem I/O.
    On failure, first check: load_dataset_jsonl's per-line error wrapping.
    """
    blob = '{"record_type":"dataset","name":"d","version":"1.0.0"}\nnot json at all\n'
    with pytest.raises(BenchmarkError, match="line 2"):
        load_dataset_jsonl(blob)


@pytest.mark.unit
def test_dataset_tasks_and_cases_by_id():
    """[Unit] dataset helpers: tasks() and cases_by_id() summarize a multi-task dataset.

    Scenario: Builds a dataset with two tasks and inspects both helper methods.
    Boundaries: Pure in-memory logic; no I/O.
    On failure, first check: BenchmarkDataset.tasks/cases_by_id.
    """
    dataset = BenchmarkDataset(
        name="d",
        version="1.0.0",
        cases=(_case(case_id="one", task="qa"), _case(case_id="two", task="summarization")),
    )
    assert dataset.tasks() == ("qa", "summarization")
    assert set(dataset.cases_by_id()) == {"one", "two"}


@pytest.mark.unit
def test_example_sample_dataset_loads_and_exercises_every_known_evaluator():
    """[Unit] example dataset: examples/benchmarks/sample-dataset.jsonl stays valid and complete.

    Scenario: Loads the shipped example dataset and checks it covers every deterministic
        evaluator id documented in docs/guides/custom-evaluators.md.
    Boundaries: Real load_dataset_jsonl against a real repository file; no network.
    On failure, first check: the example dataset file versus KNOWN_EVALUATOR_IDS (minus llm_judge).
    """
    path = _REPO_ROOT / "examples" / "benchmarks" / "sample-dataset.jsonl"
    dataset = load_dataset_jsonl(path.read_text(encoding="utf-8"))
    used_evaluators = {case.evaluator for case in dataset.cases}
    assert used_evaluators == KNOWN_EVALUATOR_IDS - {"llm_judge"}
