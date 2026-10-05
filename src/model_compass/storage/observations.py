"""SQLite-backed persistence for privacy-conscious execution observations."""

from __future__ import annotations

import builtins
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from model_compass.exceptions import StorageError
from model_compass.metrics import Observation, QualityEvidence


class ObservationStore:
    """Persist aggregate outcomes; request and message bodies are never accepted."""

    def __init__(self, database: Path) -> None:
        self._database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self._connection() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS observations (
                    id INTEGER PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    endpoint_id TEXT,
                    succeeded INTEGER NOT NULL,
                    latency_ms INTEGER NOT NULL,
                    actual_cost_usd TEXT,
                    input_tokens INTEGER,
                    output_tokens INTEGER,
                    quality_score TEXT,
                    evaluator_type TEXT
                )
                """
            )
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS quality_evidence (
                    id INTEGER PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    task TEXT NOT NULL,
                    quality_score TEXT NOT NULL,
                    sample_size INTEGER NOT NULL,
                    source TEXT NOT NULL,
                    evaluator_type TEXT NOT NULL,
                    dataset TEXT,
                    evaluated_at TEXT NOT NULL
                )
                """
            )

    def record(self, observation: Observation) -> None:
        """Store one execution observation without persisting prompt content."""
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO observations (
                    model_id, task, timestamp, endpoint_id, succeeded, latency_ms,
                    actual_cost_usd, input_tokens, output_tokens, quality_score, evaluator_type
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    observation.model_id,
                    observation.task,
                    observation.timestamp.isoformat(),
                    observation.endpoint_id,
                    int(observation.succeeded),
                    observation.latency_ms,
                    str(observation.actual_cost_usd)
                    if observation.actual_cost_usd is not None
                    else None,
                    observation.input_tokens,
                    observation.output_tokens,
                    str(observation.quality_score)
                    if observation.quality_score is not None
                    else None,
                    observation.evaluator_type,
                ),
            )

    def list(self, *, model_id: str | None = None, task: str | None = None) -> list[Observation]:
        """Return observations, optionally filtered by exact model and task."""
        clauses: list[str] = []
        parameters: list[str] = []
        if model_id is not None:
            clauses.append("model_id = ?")
            parameters.append(model_id)
        if task is not None:
            clauses.append("task = ?")
            parameters.append(task)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT model_id, task, timestamp, endpoint_id, succeeded, latency_ms, "
                f"actual_cost_usd, input_tokens, output_tokens, quality_score, evaluator_type "
                f"FROM observations{where} ORDER BY id",
                parameters,
            ).fetchall()
        return [_from_row(row) for row in rows]

    def record_quality_evidence(self, evidence: QualityEvidence) -> None:
        """Persist task-scoped quality evidence and benchmark provenance."""
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO quality_evidence (
                    model_id, task, quality_score, sample_size, source, evaluator_type,
                    dataset, evaluated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence.model_id,
                    evidence.task,
                    str(evidence.quality_score),
                    evidence.sample_size,
                    evidence.source,
                    evidence.evaluator_type,
                    evidence.dataset,
                    evidence.evaluated_at.isoformat(),
                ),
            )

    def list_quality_evidence(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[QualityEvidence]:
        """Return stored quality evidence with optional exact-match filters."""
        clauses: list[str] = []
        parameters: list[str] = []
        if model_id is not None:
            clauses.append("model_id = ?")
            parameters.append(model_id)
        if task is not None:
            clauses.append("task = ?")
            parameters.append(task)
        where = f" WHERE {' AND '.join(clauses)}" if clauses else ""
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT model_id, task, quality_score, sample_size, source, evaluator_type, "
                f"dataset, evaluated_at FROM quality_evidence{where} ORDER BY id",
                parameters,
            ).fetchall()
        return [_quality_from_row(row) for row in rows]

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        try:
            connection = sqlite3.connect(self._database)
        except sqlite3.Error as exc:
            raise StorageError("could not open analytics database") from exc
        try:
            yield connection
            connection.commit()
        except sqlite3.Error as exc:
            connection.rollback()
            raise StorageError("analytics database operation failed") from exc
        except BaseException:
            connection.rollback()
            raise
        finally:
            connection.close()


def _from_row(row: tuple[Any, ...]) -> Observation:
    return Observation(
        model_id=row[0],
        task=row[1],
        timestamp=datetime.fromisoformat(row[2]),
        endpoint_id=row[3],
        succeeded=bool(row[4]),
        latency_ms=row[5],
        actual_cost_usd=row[6],
        input_tokens=row[7],
        output_tokens=row[8],
        quality_score=row[9],
        evaluator_type=row[10],
    )


def _quality_from_row(row: tuple[Any, ...]) -> QualityEvidence:
    return QualityEvidence(
        model_id=row[0],
        task=row[1],
        quality_score=row[2],
        sample_size=row[3],
        source=row[4],
        evaluator_type=row[5],
        dataset=row[6],
        evaluated_at=datetime.fromisoformat(row[7]),
    )
