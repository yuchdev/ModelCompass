"""Deterministic benchmark evaluators: a normalized score protocol, no network calls."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from decimal import Decimal, InvalidOperation
from typing import Any, Optional, Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.benchmarks.dataset import BenchmarkCase
from model_compass.exceptions import BenchmarkError

_logger = logging.getLogger(__name__)


class EvaluationContext(BaseModel):
    """Information about the execution that produced a response, for an evaluator."""

    model_config = ConfigDict(frozen=True)

    model_id: str
    dataset_name: str
    repetition_index: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


class EvaluationResult(BaseModel):
    """A normalized, traceable evaluator outcome."""

    model_config = ConfigDict(frozen=True)

    score: Decimal
    passed: Optional[bool] = None
    evaluator_id: str
    evaluator_version: str
    explanation: str = ""
    details: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score")
    @classmethod
    def _bounded_score(cls, value: Decimal) -> Decimal:
        """Reject a score outside the inclusive [0, 1] range."""
        if not value.is_finite() or not Decimal("0") <= value <= Decimal("1"):
            raise ValueError("score must be a finite Decimal in [0, 1]")
        return value


class Evaluator(Protocol):
    """Deterministic scoring contract: a pure function of case, response, and context."""

    evaluator_id: str
    evaluator_version: str

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score one response against its case's expectation."""
        ...


class ExactMatchEvaluator:
    """Case-sensitive, whitespace-sensitive exact string match."""

    evaluator_id = "exact"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score 1.0 if response equals expected_output exactly, else 0.0."""
        passed = response == case.expected_output
        return EvaluationResult(
            score=Decimal(1) if passed else Decimal(0),
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation="exact match" if passed else "response did not exactly equal expected_output",
        )


class NormalizedExactMatchEvaluator:
    """Case-insensitive match after collapsing and trimming whitespace."""

    evaluator_id = "normalized_exact"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score 1.0 if normalized response equals normalized expected_output, else 0.0."""
        assert case.expected_output is not None
        passed = _normalize(response) == _normalize(case.expected_output)
        return EvaluationResult(
            score=Decimal(1) if passed else Decimal(0),
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation="normalized match" if passed else "response did not match after normalization",
        )


class RegexEvaluator:
    """Full-string regex match against expected_output as the pattern."""

    evaluator_id = "regex"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score 1.0 if response fully matches the expected_output pattern, else 0.0."""
        assert case.expected_output is not None
        try:
            passed = re.fullmatch(case.expected_output, response) is not None
        except re.error as exc:
            raise BenchmarkError(f"invalid regex evaluator pattern for case {case.case_id!r}: {exc}") from exc
        return EvaluationResult(
            score=Decimal(1) if passed else Decimal(0),
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation="pattern matched" if passed else "response did not fully match the expected pattern",
        )


class ContainsTermsEvaluator:
    """Required-term coverage, with partial credit and a configurable all/any policy."""

    evaluator_id = "contains_terms"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score the fraction of required_terms present in response."""
        case_sensitive = bool(case.evaluator_config.get("case_sensitive", False))
        require_all = bool(case.evaluator_config.get("require_all", True))
        haystack = response if case_sensitive else response.lower()
        terms = case.required_terms if case_sensitive else tuple(term.lower() for term in case.required_terms)
        found = [term for term in terms if term in haystack]
        fraction = Decimal(len(found)) / Decimal(len(terms))
        passed = fraction == 1 if require_all else fraction > 0
        return EvaluationResult(
            score=fraction,
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation=f"found {len(found)}/{len(terms)} required terms",
            details={"missing_terms": [term for term in case.required_terms if term.lower() not in haystack]},
        )


class JsonValidityEvaluator:
    """Syntactic JSON validity only, independent of any expected shape."""

    evaluator_id = "json_validity"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score 1.0 if response parses as JSON, else 0.0."""
        try:
            json.loads(response)
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.debug("Response failed JSON validity check: %s", exc)
            return EvaluationResult(
                score=Decimal(0),
                passed=False,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                explanation=f"response is not valid JSON: {exc}",
            )
        return EvaluationResult(
            score=Decimal(1),
            passed=True,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation="response is valid JSON",
        )


class JsonSchemaEvaluator:
    """JSON structural match: a minimal schema subset, or deep equality to expected_json."""

    evaluator_id = "json_schema"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score 1.0 if the parsed response matches the case's schema or expected_json."""
        try:
            parsed = json.loads(response)
        except (json.JSONDecodeError, TypeError) as exc:
            _logger.debug("Response failed JSON schema check: %s", exc)
            return EvaluationResult(
                score=Decimal(0),
                passed=False,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                explanation=f"response is not valid JSON: {exc}",
            )
        schema = case.evaluator_config.get("schema")
        if schema is not None:
            errors = _validate_schema(parsed, schema, path="$")
            passed = not errors
            return EvaluationResult(
                score=Decimal(1) if passed else Decimal(0),
                passed=passed,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                explanation="matched schema" if passed else "; ".join(errors),
                details={"errors": errors},
            )
        passed = parsed == case.expected_json
        return EvaluationResult(
            score=Decimal(1) if passed else Decimal(0),
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation="matched expected_json" if passed else "response did not deep-equal expected_json",
        )


class NumericToleranceEvaluator:
    """Numeric comparison within an absolute or relative tolerance."""

    evaluator_id = "numeric_tolerance"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        """Score 1.0 if response is numerically within tolerance of expected_output."""
        assert case.expected_output is not None
        assert case.numeric_tolerance is not None
        try:
            actual = Decimal(response.strip())
            expected = Decimal(case.expected_output)
        except (InvalidOperation, ValueError) as exc:
            _logger.debug("Response failed numeric parsing: %s", exc)
            return EvaluationResult(
                score=Decimal(0),
                passed=False,
                evaluator_id=self.evaluator_id,
                evaluator_version=self.evaluator_version,
                explanation=f"response is not numeric: {exc}",
            )
        relative = bool(case.evaluator_config.get("relative", False))
        tolerance = case.numeric_tolerance * abs(expected) if relative else case.numeric_tolerance
        difference = abs(actual - expected)
        passed = difference <= tolerance
        return EvaluationResult(
            score=Decimal(1) if passed else Decimal(0),
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation=f"|{actual} - {expected}| = {difference} vs tolerance {tolerance}",
            details={"actual": str(actual), "expected": str(expected), "difference": str(difference)},
        )


DETERMINISTIC_EVALUATORS: dict[str, Evaluator] = {
    evaluator.evaluator_id: evaluator
    for evaluator in (
        ExactMatchEvaluator(),
        NormalizedExactMatchEvaluator(),
        RegexEvaluator(),
        ContainsTermsEvaluator(),
        JsonValidityEvaluator(),
        JsonSchemaEvaluator(),
        NumericToleranceEvaluator(),
    )
}


def resolve_evaluator(evaluator_id: str, *, custom_evaluators: Optional[Mapping[str, Evaluator]] = None) -> Evaluator:
    """Resolve an evaluator id, preferring caller-supplied custom evaluators."""
    custom = custom_evaluators or {}
    if evaluator_id in custom:
        return custom[evaluator_id]
    if evaluator_id in DETERMINISTIC_EVALUATORS:
        return DETERMINISTIC_EVALUATORS[evaluator_id]
    raise BenchmarkError(f"no evaluator registered for id: {evaluator_id!r}")


def _normalize(text: str) -> str:
    """Lowercase, trim, and collapse internal whitespace."""
    return " ".join(text.lower().split())


_SCALAR_TYPES: dict[str, type] = {
    "string": str,
    "number": (int, float),  # type: ignore[dict-item]
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def _validate_schema(value: Any, schema: Mapping[str, Any], *, path: str) -> list[str]:
    """Recursively validate a value against a minimal JSON-Schema-like subset."""
    errors: list[str] = []
    expected_type = schema.get("type")
    if expected_type == "object":
        if not isinstance(value, dict):
            return [f"{path}: expected object, got {type(value).__name__}"]
        for key in schema.get("required", []):
            if key not in value:
                errors.append(f"{path}: missing required property {key!r}")
        properties = schema.get("properties", {})
        for key, sub_schema in properties.items():
            if key in value:
                errors.extend(_validate_schema(value[key], sub_schema, path=f"{path}.{key}"))
    elif expected_type == "array":
        if not isinstance(value, list):
            return [f"{path}: expected array, got {type(value).__name__}"]
        item_schema = schema.get("items")
        if item_schema is not None:
            for index, item in enumerate(value):
                errors.extend(_validate_schema(item, item_schema, path=f"{path}[{index}]"))
    elif expected_type in _SCALAR_TYPES:
        python_type = _SCALAR_TYPES[expected_type]
        if expected_type == "number" and isinstance(value, bool):
            errors.append(f"{path}: expected number, got boolean")
        elif expected_type == "integer" and (isinstance(value, bool) or not isinstance(value, int)):
            errors.append(f"{path}: expected integer, got {type(value).__name__}")
        elif not isinstance(value, python_type):
            errors.append(f"{path}: expected {expected_type}, got {type(value).__name__}")
    elif expected_type is not None:
        errors.append(f"{path}: unsupported schema type {expected_type!r}")
    return errors
