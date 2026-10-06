from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from model_compass.benchmarks import (
    ExternalEvidenceRecord,
    import_external_evidence,
    load_external_evidence_jsonl,
    normalize_external_score,
)
from model_compass.exceptions import BenchmarkError


def _record(**overrides: object) -> ExternalEvidenceRecord:
    """Build a minimal external evidence record, overriding selected fields."""
    defaults: dict[str, object] = {
        "source": "leaderboard-x",
        "benchmark": "mmlu",
        "model": "provider:model",
        "task": "reasoning",
        "score": Decimal("82"),
        "scale": "0-100",
        "retrieved_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return ExternalEvidenceRecord.model_validate(defaults)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("scale", "score", "expected"),
    [
        ("0-1", Decimal("0.5"), Decimal("0.5")),
        ("0-100", Decimal("50"), Decimal("0.5")),
        ("percentage", Decimal("25"), Decimal("0.25")),
        (None, Decimal("0.5"), None),
        ("unknown-scale", Decimal("5"), None),
    ],
)
def test_normalize_external_score_known_and_unknown_scales(scale: object, score: Decimal, expected: object):
    """[Unit] score normalization: known scales normalize to [0, 1]; unknown scales return None.

    Scenario: Normalizes scores on each known scale and on a missing or unrecognized scale.
    Boundaries: Pure arithmetic over in-memory values; no I/O.
    On failure, first check: normalize_external_score's KNOWN_SCALES lookup and bounds math.
    """
    assert normalize_external_score(score, scale) == expected


@pytest.mark.unit
def test_normalize_external_score_rejects_out_of_bounds_score():
    """[Unit] scale bounds: a score outside its declared scale's bounds raises.

    Scenario: Normalizes a score of 150 on a declared 0-100 scale.
    Boundaries: Pure arithmetic over in-memory values; no I/O.
    On failure, first check: normalize_external_score's bounds check.
    """
    with pytest.raises(BenchmarkError, match="outside"):
        normalize_external_score(Decimal("150"), "0-100")


@pytest.mark.unit
def test_import_external_evidence_produces_normalized_quality_evidence():
    """[Unit] import mechanism: known-scale records become normalized, provenance-tagged evidence.

    Scenario: Imports one record on a known scale and checks the resulting evidence fields.
    Boundaries: Pure in-memory conversion; no network access, no scraping.
    On failure, first check: import_external_evidence's QualityEvidence construction.
    """
    (evidence,) = import_external_evidence([_record()])
    assert evidence.model_id == "provider:model"
    assert evidence.task == "reasoning"
    assert evidence.score == Decimal("0.82")
    assert evidence.source == "imported:leaderboard-x"
    assert evidence.sample_count == 1
    assert evidence.metadata["original_score"] == "82"


@pytest.mark.unit
def test_import_external_evidence_unknown_scale_raises_by_default_or_skips():
    """[Unit] unknown scale handling: raise by default, or skip when explicitly requested.

    Scenario: Imports a record with no declared scale, under both policies.
    Boundaries: Pure in-memory conversion; no I/O.
    On failure, first check: import_external_evidence's on_unknown_scale branch.
    """
    record = _record(scale=None)
    with pytest.raises(BenchmarkError, match="unknown or missing scale"):
        import_external_evidence([record])
    assert import_external_evidence([record], on_unknown_scale="skip") == ()


@pytest.mark.unit
def test_load_external_evidence_jsonl_parses_one_record_per_line():
    """[Unit] JSONL parsing: one record is parsed per non-blank line.

    Scenario: Parses two valid lines and one blank line.
    Boundaries: Pure parsing logic over an in-memory string; no filesystem I/O.
    On failure, first check: load_external_evidence_jsonl's per-line parsing.
    """
    blob = (
        '{"source":"a","benchmark":"b","model":"m","task":"t","score":"1","scale":"0-1",'
        '"retrieved_at":"2026-01-01T00:00:00Z"}\n'
        "\n"
        '{"source":"a2","benchmark":"b","model":"m2","task":"t","score":"50","scale":"0-100",'
        '"retrieved_at":"2026-01-01T00:00:00Z"}\n'
    )
    records = load_external_evidence_jsonl(blob)
    assert len(records) == 2
    assert records[0].source == "a"
    assert records[1].model == "m2"


@pytest.mark.unit
def test_load_external_evidence_jsonl_rejects_invalid_record():
    """[Unit] malformed external evidence: an invalid record raises BenchmarkError with its line.

    Scenario: Parses a line missing required fields.
    Boundaries: Pure parsing logic; no I/O.
    On failure, first check: load_external_evidence_jsonl's error wrapping.
    """
    with pytest.raises(BenchmarkError, match="line 1"):
        load_external_evidence_jsonl('{"source":"a"}')
