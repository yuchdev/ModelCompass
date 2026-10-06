from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from model_compass.benchmarks import (
    BenchmarkCase,
    ContainsTermsEvaluator,
    EvaluationContext,
    EvaluationResult,
    ExactMatchEvaluator,
    JsonSchemaEvaluator,
    JsonValidityEvaluator,
    NormalizedExactMatchEvaluator,
    NumericToleranceEvaluator,
    RegexEvaluator,
    resolve_evaluator,
)
from model_compass.exceptions import BenchmarkError

_CONTEXT = EvaluationContext(model_id="test:model", dataset_name="fixture")


def _case(**overrides: object) -> BenchmarkCase:
    """Build a minimal case, overriding selected fields."""
    defaults: dict[str, object] = {"case_id": "c", "task": "qa", "input_text": "q", "evaluator": "exact"}
    defaults.update(overrides)
    return BenchmarkCase.model_validate(defaults)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("expected", "response", "passed"),
    [("answer", "answer", True), ("answer", "Answer", False), ("answer", "answer ", False)],
)
def test_exact_match_evaluator(expected: str, response: str, passed: bool):
    """[Unit] exact match: case and whitespace sensitive equality.

    Scenario: Scores exact and near-miss responses against an expected string.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: ExactMatchEvaluator's string equality.
    """
    case = _case(evaluator="exact", expected_output=expected)
    result = ExactMatchEvaluator().evaluate(case, response, _CONTEXT)
    assert result.passed is passed
    assert result.score == (1 if passed else 0)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("expected", "response", "passed"),
    [("Answer", "answer", True), ("  a   b ", "A B", True), ("answer", "other", False)],
)
def test_normalized_exact_match_evaluator(expected: str, response: str, passed: bool):
    """[Unit] normalized exact match: case-insensitive, whitespace-collapsed equality.

    Scenario: Scores responses that differ only in case or whitespace from expected.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: NormalizedExactMatchEvaluator's normalization.
    """
    case = _case(evaluator="normalized_exact", expected_output=expected)
    result = NormalizedExactMatchEvaluator().evaluate(case, response, _CONTEXT)
    assert result.passed is passed


@pytest.mark.unit
def test_regex_evaluator_matches_full_string_and_raises_on_invalid_pattern():
    """[Unit] regex evaluator: requires a full match and wraps invalid patterns.

    Scenario: Matches a valid pattern, rejects a partial match, and raises on a broken pattern.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: RegexEvaluator's fullmatch call and BenchmarkError wrapping.
    """
    case = _case(evaluator="regex", expected_output=r"answer-\d+")
    assert RegexEvaluator().evaluate(case, "answer-42", _CONTEXT).passed is True
    assert RegexEvaluator().evaluate(case, "prefix-answer-42", _CONTEXT).passed is False

    broken = _case(evaluator="regex", expected_output="(")
    with pytest.raises(BenchmarkError, match="invalid regex"):
        RegexEvaluator().evaluate(broken, "anything", _CONTEXT)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("required_terms", "response", "require_all", "passed", "score"),
    [
        (("alpha", "beta"), "alpha and beta here", True, True, Decimal(1)),
        (("alpha", "beta"), "only alpha here", True, False, Decimal("0.5")),
        (("alpha", "beta"), "only alpha here", False, True, Decimal("0.5")),
        (("alpha", "beta"), "neither term", False, False, Decimal(0)),
    ],
)
def test_contains_terms_evaluator_partial_credit_and_require_all(
    required_terms: tuple[str, ...], response: str, require_all: bool, passed: bool, score: Decimal
):
    """[Unit] contains terms: scores the fraction of required terms found, with an all/any policy.

    Scenario: Scores responses containing all, some, or none of the required terms.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: ContainsTermsEvaluator's fraction scoring and require_all policy.
    """
    case = _case(
        evaluator="contains_terms", required_terms=required_terms, evaluator_config={"require_all": require_all}
    )
    result = ContainsTermsEvaluator().evaluate(case, response, _CONTEXT)
    assert result.score == score
    assert result.passed is passed


@pytest.mark.unit
def test_contains_terms_case_sensitivity_is_configurable():
    """[Unit] contains terms case sensitivity: case_sensitive flag changes matching behavior.

    Scenario: Scores a case-differing response with case sensitivity on and off.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: ContainsTermsEvaluator's case_sensitive branch.
    """
    case_insensitive = _case(evaluator="contains_terms", required_terms=("Alpha",))
    assert ContainsTermsEvaluator().evaluate(case_insensitive, "alpha present", _CONTEXT).passed is True

    case_sensitive = _case(
        evaluator="contains_terms", required_terms=("Alpha",), evaluator_config={"case_sensitive": True}
    )
    assert ContainsTermsEvaluator().evaluate(case_sensitive, "alpha present", _CONTEXT).passed is False


@pytest.mark.unit
@pytest.mark.parametrize(("response", "passed"), [('{"a": 1}', True), ("not json", False), ("[1, 2]", True)])
def test_json_validity_evaluator_checks_syntax_only(response: str, passed: bool):
    """[Unit] JSON validity: scores syntactic validity regardless of shape.

    Scenario: Scores a valid object, invalid text, and a valid array.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: JsonValidityEvaluator's json.loads call.
    """
    case = _case(evaluator="json_validity", input_text="q")
    result = JsonValidityEvaluator().evaluate(case, response, _CONTEXT)
    assert result.passed is passed


@pytest.mark.unit
def test_json_schema_evaluator_deep_equality_mode():
    """[Unit] JSON schema deep equality: matches expected_json exactly when no schema is given.

    Scenario: Scores a response that deep-equals expected_json and one that does not.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: JsonSchemaEvaluator's expected_json deep-equality branch.
    """
    case = _case(evaluator="json_schema", expected_output=None, expected_json={"a": 1})
    assert JsonSchemaEvaluator().evaluate(case, '{"a": 1}', _CONTEXT).passed is True
    assert JsonSchemaEvaluator().evaluate(case, '{"a": 2}', _CONTEXT).passed is False
    assert JsonSchemaEvaluator().evaluate(case, "not json", _CONTEXT).passed is False


@pytest.mark.unit
def test_json_schema_evaluator_structural_mode():
    """[Unit] JSON schema structural match: validates required keys and types.

    Scenario: Scores responses against a schema requiring an object with a typed, required field.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: JsonSchemaEvaluator's minimal schema-subset validator.
    """
    schema = {
        "type": "object",
        "required": ["name", "count"],
        "properties": {"name": {"type": "string"}, "count": {"type": "integer"}},
    }
    case = _case(evaluator="json_schema", expected_output=None, evaluator_config={"schema": schema})
    assert JsonSchemaEvaluator().evaluate(case, '{"name": "x", "count": 3}', _CONTEXT).passed is True
    missing_key = JsonSchemaEvaluator().evaluate(case, '{"name": "x"}', _CONTEXT)
    assert missing_key.passed is False
    assert "count" in missing_key.explanation
    wrong_type = JsonSchemaEvaluator().evaluate(case, '{"name": "x", "count": "three"}', _CONTEXT)
    assert wrong_type.passed is False


@pytest.mark.unit
def test_json_schema_evaluator_nested_array_and_boolean_types():
    """[Unit] JSON schema nested types: array items and boolean/null types validate recursively.

    Scenario: Validates a schema with an array of objects and a boolean field.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: JsonSchemaEvaluator's array 'items' recursion.
    """
    schema = {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {"type": "object", "required": ["id"], "properties": {"id": {"type": "integer"}}},
            },
            "active": {"type": "boolean"},
        },
    }
    case = _case(evaluator="json_schema", expected_output=None, evaluator_config={"schema": schema})
    good = JsonSchemaEvaluator().evaluate(case, '{"items": [{"id": 1}, {"id": 2}], "active": true}', _CONTEXT)
    assert good.passed is True
    bad = JsonSchemaEvaluator().evaluate(case, '{"items": [{"id": "x"}], "active": true}', _CONTEXT)
    assert bad.passed is False


@pytest.mark.unit
@pytest.mark.parametrize(
    ("expected", "tolerance", "relative", "response", "passed"),
    [
        ("3.14", "0.01", False, "3.145", True),
        ("3.14", "0.01", False, "3.2", False),
        ("100", "0.05", True, "104", True),
        ("100", "0.05", True, "110", False),
    ],
)
def test_numeric_tolerance_evaluator(expected: str, tolerance: str, relative: bool, response: str, passed: bool):
    """[Unit] numeric tolerance: absolute and relative tolerance comparisons.

    Scenario: Scores numeric responses within and outside absolute and relative tolerances.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: NumericToleranceEvaluator's tolerance computation.
    """
    case = _case(
        evaluator="numeric_tolerance",
        expected_output=expected,
        numeric_tolerance=Decimal(tolerance),
        evaluator_config={"relative": relative},
    )
    result = NumericToleranceEvaluator().evaluate(case, response, _CONTEXT)
    assert result.passed is passed


@pytest.mark.unit
def test_numeric_tolerance_evaluator_rejects_non_numeric_response():
    """[Unit] numeric tolerance non-numeric input: a non-numeric response scores 0 without raising.

    Scenario: Scores a non-numeric response against a numeric expectation.
    Boundaries: Pure evaluator logic; no I/O.
    On failure, first check: NumericToleranceEvaluator's Decimal-parsing except branch.
    """
    case = _case(evaluator="numeric_tolerance", expected_output="1", numeric_tolerance=Decimal("0.1"))
    result = NumericToleranceEvaluator().evaluate(case, "not a number", _CONTEXT)
    assert result.passed is False
    assert result.score == 0


@pytest.mark.unit
def test_evaluation_result_rejects_out_of_bounds_score():
    """[Unit] score bounds: EvaluationResult rejects scores outside the inclusive [0, 1] range.

    Scenario: Constructs EvaluationResult with scores below 0, above 1, and at both bounds.
    Boundaries: Pure pydantic validation; no I/O.
    On failure, first check: EvaluationResult's bounded-score validator.
    """
    for bad_score in (Decimal("-0.01"), Decimal("1.01")):
        with pytest.raises(ValidationError):
            EvaluationResult(score=bad_score, evaluator_id="x", evaluator_version="1.0.0")
    for good_score in (Decimal(0), Decimal(1), Decimal("0.5")):
        assert EvaluationResult(score=good_score, evaluator_id="x", evaluator_version="1.0.0").score == good_score


@pytest.mark.unit
def test_resolve_evaluator_prefers_custom_over_builtin_and_raises_for_unknown():
    """[Unit] evaluator resolution: custom evaluators take precedence; unknown ids raise.

    Scenario: Resolves a built-in id, a custom override of a built-in id, and an unknown id.
    Boundaries: Pure registry lookup; no I/O.
    On failure, first check: resolve_evaluator's custom-first lookup order.
    """
    assert resolve_evaluator("exact") is resolve_evaluator("exact")
    custom = ExactMatchEvaluator()
    assert resolve_evaluator("exact", custom_evaluators={"exact": custom}) is custom
    with pytest.raises(BenchmarkError, match="no evaluator registered"):
        resolve_evaluator("totally_unknown")
