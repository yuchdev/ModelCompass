"""JSONL-based benchmark dataset format with deterministic content identity."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable
from decimal import Decimal
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from model_compass.exceptions import BenchmarkError

DATASET_SCHEMA_VERSION = 1

#: Evaluator ids with a built-in deterministic implementation; any other string is
#: treated as a custom evaluator id and is not validated against expectation shape.
KNOWN_EVALUATOR_IDS: frozenset[str] = frozenset(
    {
        "exact",
        "normalized_exact",
        "regex",
        "contains_terms",
        "json_validity",
        "json_schema",
        "numeric_tolerance",
        "llm_judge",
    }
)

_REQUIRES_EXPECTED_OUTPUT = frozenset({"exact", "normalized_exact", "regex", "numeric_tolerance"})


class BenchmarkCase(BaseModel):
    """One dataset case: a request plus an evaluation payload, not forced to exact match."""

    model_config = ConfigDict(frozen=True)

    schema_version: int = DATASET_SCHEMA_VERSION
    case_id: str = Field(min_length=1)
    task: str = Field(min_length=1)
    messages: Optional[tuple[dict[str, Any], ...]] = None
    input_text: Optional[str] = None
    tags: tuple[str, ...] = ()
    requirements: dict[str, Any] = Field(default_factory=dict)
    evaluator: str = Field(min_length=1)
    expected_output: Optional[str] = None
    expected_json: Optional[Any] = None
    required_terms: tuple[str, ...] = ()
    numeric_tolerance: Optional[Decimal] = None
    evaluator_config: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_input(self) -> BenchmarkCase:
        """Require exactly one of messages or input_text, and plausible expectations."""
        if (self.messages is None) == (self.input_text is None):
            raise ValueError("exactly one of messages or input_text must be set")
        if self.evaluator in _REQUIRES_EXPECTED_OUTPUT and self.expected_output is None:
            raise ValueError(f"evaluator {self.evaluator!r} requires expected_output")
        if self.evaluator == "numeric_tolerance" and self.numeric_tolerance is None:
            raise ValueError("evaluator 'numeric_tolerance' requires numeric_tolerance")
        if self.evaluator == "contains_terms" and not self.required_terms:
            raise ValueError("evaluator 'contains_terms' requires required_terms")
        if self.evaluator == "json_schema" and "schema" not in self.evaluator_config and self.expected_json is None:
            raise ValueError("evaluator 'json_schema' requires evaluator_config['schema'] or expected_json")
        return self

    def prompt_messages(self) -> tuple[dict[str, Any], ...]:
        """Return the case's request as chat messages, synthesizing one from input_text."""
        if self.messages is not None:
            return self.messages
        return ({"role": "user", "content": self.input_text},)


class BenchmarkDataset(BaseModel):
    """A named, versioned, content-addressed collection of benchmark cases."""

    model_config = ConfigDict(frozen=True)

    name: str = Field(min_length=1)
    version: str = Field(min_length=1)
    description: Optional[str] = None
    cases: tuple[BenchmarkCase, ...] = Field(min_length=1)

    @field_validator("cases")
    @classmethod
    def _unique_case_ids(cls, value: tuple[BenchmarkCase, ...]) -> tuple[BenchmarkCase, ...]:
        """Reject a dataset containing duplicate case ids."""
        case_ids = [case.case_id for case in value]
        duplicates = sorted({case_id for case_id in case_ids if case_ids.count(case_id) > 1})
        if duplicates:
            raise ValueError(f"duplicate case ids: {', '.join(duplicates)}")
        return value

    @property
    def content_hash(self) -> str:
        """Return a deterministic SHA-256 hash over the dataset's case content.

        Computed on demand (not stored) so it can never drift from the cases it
        describes; two datasets with identical cases always hash identically
        regardless of case order.
        """
        ordered = sorted(self.cases, key=lambda case: case.case_id)
        payload = [_json_safe(case.model_dump(mode="python")) for case in ordered]
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
        return hashlib.sha256(encoded.encode("utf-8")).hexdigest()

    @property
    def identity(self) -> DatasetIdentity:
        """Return the dataset's deterministic identity: name, version, content hash."""
        return DatasetIdentity(name=self.name, version=self.version, content_hash=self.content_hash)

    def tasks(self) -> tuple[str, ...]:
        """Return the distinct tasks present in this dataset, sorted."""
        return tuple(sorted({case.task for case in self.cases}))

    def cases_by_id(self) -> dict[str, BenchmarkCase]:
        """Return cases indexed by case_id."""
        return {case.case_id: case for case in self.cases}


class DatasetIdentity(BaseModel):
    """Deterministic identity for one dataset snapshot."""

    model_config = ConfigDict(frozen=True)

    name: str
    version: str
    content_hash: str


def dump_dataset_jsonl(dataset: BenchmarkDataset) -> str:
    """Serialize a dataset to JSONL: one header record, then one record per case."""
    header = {
        "record_type": "dataset",
        "schema_version": DATASET_SCHEMA_VERSION,
        "name": dataset.name,
        "version": dataset.version,
        "description": dataset.description,
    }
    lines = [_dump_line(header)]
    for case in dataset.cases:
        record = {"record_type": "case", **_json_safe(case.model_dump(mode="python"))}
        lines.append(_dump_line(record))
    return "".join(lines)


def load_dataset_jsonl(
    content: str,
    *,
    name: Optional[str] = None,
    version: Optional[str] = None,
) -> BenchmarkDataset:
    """Parse a JSONL dataset, using an embedded header or the given name/version.

    Explicit `name`/`version` arguments take precedence over an embedded header
    record, letting callers pin an identity independent of file contents.
    """
    header_name: Optional[str] = name
    header_version: Optional[str] = version
    description: Optional[str] = None
    cases: list[BenchmarkCase] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            record = json.loads(line)
            if not isinstance(record, dict):
                raise TypeError("dataset JSONL record must be an object")
            record_type = record.get("record_type")
            if record_type == "dataset":
                header_name = header_name or record.get("name")
                header_version = header_version or record.get("version")
                description = record.get("description")
            elif record_type == "case":
                case_data = {key: value for key, value in record.items() if key != "record_type"}
                cases.append(BenchmarkCase.model_validate(case_data))
            else:
                raise ValueError(f"unknown dataset record_type: {record_type!r}")
        except (TypeError, ValueError) as exc:
            raise BenchmarkError(f"invalid dataset JSONL record on line {line_number}: {exc}") from exc
    if header_name is None or header_version is None:
        raise BenchmarkError("dataset name and version must be given explicitly or via a dataset header record")
    if not cases:
        raise BenchmarkError("dataset must contain at least one case")
    return BenchmarkDataset(name=header_name, version=header_version, description=description, cases=tuple(cases))


def _dump_line(record: dict[str, Any]) -> str:
    """Serialize one JSONL record deterministically, terminated with a newline."""
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"


def _json_safe(value: Any) -> Any:
    """Recursively convert a value into JSON-serializable primitives."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {key: _json_safe(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_json_safe(item) for item in value]
    return value


def iter_case_tasks(cases: Iterable[BenchmarkCase]) -> frozenset[str]:
    """Return the distinct task names used by the given cases."""
    return frozenset(case.task for case in cases)
