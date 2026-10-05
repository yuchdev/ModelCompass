"""SQLite-backed persistence for privacy-conscious execution observations."""

from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from model_compass.metrics import Observation


class ObservationStore:
    """Persist aggregate outcomes; request and message bodies are never accepted."""

    def __init__(self, database: Path) -> None:
        self._database = database
        database.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
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

    def record(self, observation: Observation) -> None:
        """Store one execution observation without persisting prompt content."""
        with self._connect() as connection:
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
        with self._connect() as connection:
            rows = connection.execute(
                f"SELECT model_id, task, timestamp, endpoint_id, succeeded, latency_ms, "
                f"actual_cost_usd, input_tokens, output_tokens, quality_score, evaluator_type "
                f"FROM observations{where} ORDER BY id",
                parameters,
            ).fetchall()
        return [_from_row(row) for row in rows]

    def _connect(self) -> sqlite3.Connection:
        return sqlite3.connect(self._database)


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
