"""Generic import of externally obtained benchmark records; no scraping, no guessing."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from model_compass.domain import QualityEvidence, parse_decimal
from model_compass.exceptions import BenchmarkError

#: Known scales mapped to their (low, high) bounds. Unlisted scales are never
#: guessed at; callers must normalize them before import or let import skip/raise.
KNOWN_SCALES: dict[str, tuple[Decimal, Decimal]] = {
    "0-1": (Decimal(0), Decimal(1)),
    "0-100": (Decimal(0), Decimal(100)),
    "percentage": (Decimal(0), Decimal(100)),
}


class ExternalEvidenceRecord(BaseModel):
    """One externally reported benchmark score, exactly as retrieved."""

    model_config = ConfigDict(frozen=True)

    source: str = Field(min_length=1)
    benchmark: str = Field(min_length=1)
    model: str = Field(min_length=1)
    task: str = Field(min_length=1)
    score: Decimal
    scale: Optional[str] = None
    retrieved_at: datetime
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("score", mode="before")
    @classmethod
    def _parse_score(cls, value: object) -> Decimal:
        """Parse the raw reported score into a Decimal."""
        return parse_decimal(value)

    @field_validator("retrieved_at")
    @classmethod
    def _normalize_timestamp(cls, value: datetime) -> datetime:
        """Require a timezone-aware retrieval time."""
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("retrieved_at must include a timezone")
        return value


def normalize_external_score(score: Decimal, scale: Optional[str]) -> Optional[Decimal]:
    """Normalize a score to [0, 1] for a known scale; return None for an unknown scale."""
    if scale is None:
        return None
    bounds = KNOWN_SCALES.get(scale)
    if bounds is None:
        return None
    low, high = bounds
    if not low <= score <= high:
        raise BenchmarkError(f"score {score} is outside the declared {scale!r} scale bounds")
    return (score - low) / (high - low)


def import_external_evidence(
    records: Iterable[ExternalEvidenceRecord],
    *,
    on_unknown_scale: Literal["skip", "raise"] = "raise",
) -> tuple[QualityEvidence, ...]:
    """Convert external records with a known scale into normalized quality evidence.

    Each record becomes its own evidence entry (`sample_count=1`); the caller's
    quality resolution policy decides how imported evidence competes with local
    benchmark evidence. Records on an unknown scale are skipped or rejected,
    never silently assumed to already be in [0, 1].
    """
    results: list[QualityEvidence] = []
    for record in records:
        normalized = normalize_external_score(record.score, record.scale)
        if normalized is None:
            if on_unknown_scale == "raise":
                raise BenchmarkError(
                    f"external record from {record.source!r} has an unknown or missing scale: {record.scale!r}"
                )
            continue
        results.append(
            QualityEvidence(
                model_id=record.model,
                task=record.task,
                score=normalized,
                evaluator=record.benchmark,
                source=f"imported:{record.source}",
                sample_count=1,
                observed_at=record.retrieved_at,
                metadata={"original_score": str(record.score), "scale": record.scale, **record.metadata},
            )
        )
    return tuple(results)


def load_external_evidence_jsonl(content: str) -> tuple[ExternalEvidenceRecord, ...]:
    """Parse one externally obtained benchmark record per JSONL line."""
    records: list[ExternalEvidenceRecord] = []
    for line_number, line in enumerate(content.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            payload = json.loads(line)
            if not isinstance(payload, dict):
                raise TypeError("external evidence JSONL record must be an object")
            records.append(ExternalEvidenceRecord.model_validate(payload))
        except (TypeError, ValueError) as exc:
            raise BenchmarkError(f"invalid external evidence record on line {line_number}: {exc}") from exc
    return tuple(records)
