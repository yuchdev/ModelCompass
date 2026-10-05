"""SQLite and in-memory implementations of the observation storage protocol."""

from __future__ import annotations

import builtins
import hashlib
import json
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from threading import RLock
from typing import Any

from model_compass.config import default_paths
from model_compass.domain import (
    BenchmarkResult,
    BenchmarkRun,
    Observation,
    PayloadPolicy,
    QualityEvidence,
)
from model_compass.exceptions import ModelCompassError, StorageError
from model_compass.metrics.observations import ObservationSummary, summarize_observations
from model_compass.metrics.task_observations import (
    Observation as TaskObservation,
)
from model_compass.metrics.task_observations import (
    QualityEvidence as TaskQualityEvidence,
)

SCHEMA_VERSION = 2


class ObservationStoreError(StorageError):
    """Base exception for observation storage failures."""


class UnsupportedSchemaVersionError(ObservationStoreError):
    """Raised when a database uses a schema version newer than this package."""


class ImportRecordError(ModelCompassError, ValueError):
    """A JSONL record is invalid; the exception includes its source line."""


class SQLiteObservationStore:
    """SQLite-backed observation storage with lazy database initialization."""

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        payload_policy: PayloadPolicy = PayloadPolicy.NONE,
    ) -> None:
        self.path = (
            str(path)
            if path is not None
            else str(default_paths().data_dir / "observations.sqlite3")
        )
        self.payload_policy = PayloadPolicy(payload_policy)
        self._lock = RLock()
        self._memory_connection: sqlite3.Connection | None = None

    def record_observation(
        self, observation: Observation, *, deduplicate: bool = False
    ) -> Observation:
        self.record_observations([observation], deduplicate=deduplicate)
        return _apply_payload_policy(observation, self.payload_policy)

    def record(self, observation: TaskObservation) -> None:
        """Store a task-selection observation using the shared persistent schema."""
        self.record_observation(_stored_observation(observation))

    def list(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[TaskObservation]:
        """Return observations in the task-selection API's normalized shape."""
        return [
            _task_observation(row)
            for row in self.query_observations(model_id=model_id, task=task)
            if row.latency_ms is not None
        ]

    def record_observations(
        self, observations: builtins.list[Observation], *, deduplicate: bool = False
    ) -> int:
        if not observations:
            return 0
        prepared = [_apply_payload_policy(row, self.payload_policy) for row in observations]
        placeholders = ",".join("?" for _ in _OBSERVATION_COLUMNS)
        verb = "INSERT OR IGNORE" if deduplicate else "INSERT"
        with self._transaction() as connection:
            before = connection.total_changes
            connection.executemany(
                f"{verb} INTO observations ({','.join(_OBSERVATION_COLUMNS)}) "
                f"VALUES ({placeholders})",
                [_observation_values(row) for row in prepared],
            )
            recorded = connection.total_changes - before
            payloads = [
                (row.observation_id, row.prompt, row.response)
                for row in prepared
                if row.prompt is not None or row.response is not None
            ]
            if payloads:
                connection.executemany(
                    f"{verb} INTO observation_payloads (observation_id, prompt, response) "
                    "VALUES (?, ?, ?)",
                    payloads,
                )
            return recorded

    def query_observations(
        self,
        *,
        model_id: str | None = None,
        task: str | None = None,
        endpoint: str | None = None,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        limit: int | None = None,
    ) -> builtins.list[Observation]:
        filters, values = _observation_filters(
            model_id=model_id,
            task=task,
            endpoint=endpoint,
            since=since,
            recent=recent,
            now_utc=now_utc,
            limit=limit,
        )
        sql = (
            "SELECT observations.*, observation_payloads.prompt, observation_payloads.response "
            "FROM observations LEFT JOIN observation_payloads USING (observation_id)"
        )
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY timestamp, observation_id"
        if limit is not None:
            sql += " LIMIT ?"
            values.append(limit)
        with self._connection() as connection:
            self._ensure_schema(connection)
            return [_observation_from_row(row) for row in connection.execute(sql, values)]

    def summarize_model(
        self,
        model_id: str,
        *,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        task: str | None = None,
        endpoint: str | None = None,
        min_samples: int = 5,
    ) -> ObservationSummary:
        rows = self.query_observations(
            model_id=model_id,
            task=task,
            endpoint=endpoint,
            since=since,
            recent=recent,
            now_utc=now_utc,
        )
        return summarize_observations(rows, min_samples=min_samples)

    def summarize_task(
        self,
        task: str,
        *,
        model_id: str | None = None,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        endpoint: str | None = None,
        min_samples: int = 5,
    ) -> ObservationSummary:
        rows = self.query_observations(
            model_id=model_id,
            task=task,
            endpoint=endpoint,
            since=since,
            recent=recent,
            now_utc=now_utc,
        )
        return summarize_observations(rows, min_samples=min_samples)

    def record_benchmark_run(self, run: BenchmarkRun) -> BenchmarkRun:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO benchmark_runs (
                    run_id, dataset_id, dataset_version, dataset_hash, started_at,
                    ended_at, runner_version, configuration_json, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.run_id,
                    run.dataset_id,
                    run.dataset_version,
                    run.dataset_hash,
                    _timestamp(run.started_at),
                    _timestamp(run.ended_at) if run.ended_at else None,
                    run.runner_version,
                    _json(run.configuration),
                    run.status,
                ),
            )
        return run

    def query_benchmark_runs(self) -> builtins.list[BenchmarkRun]:
        with self._connection() as connection:
            self._ensure_schema(connection)
            rows = connection.execute("SELECT * FROM benchmark_runs ORDER BY run_id")
            return [_benchmark_run_from_row(row) for row in rows]

    def record_benchmark_result(self, result: BenchmarkResult) -> BenchmarkResult:
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO benchmark_results (
                    run_id, case_id, model_id, score, evaluator, cost, latency_ms, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                _benchmark_result_values(result),
            )
        return result

    def query_benchmark_results(
        self, *, run_id: str | None = None
    ) -> builtins.list[BenchmarkResult]:
        sql = "SELECT * FROM benchmark_results"
        values: tuple[str, ...] = ()
        if run_id is not None:
            sql += " WHERE run_id = ?"
            values = (run_id,)
        sql += " ORDER BY run_id, case_id, model_id"
        with self._connection() as connection:
            self._ensure_schema(connection)
            return [_benchmark_result_from_row(row) for row in connection.execute(sql, values)]

    def record_quality_evidence(
        self, evidence: QualityEvidence | TaskQualityEvidence
    ) -> QualityEvidence | TaskQualityEvidence:
        if isinstance(evidence, TaskQualityEvidence):
            evidence = _stored_quality_evidence(evidence)
        with self._transaction() as connection:
            connection.execute(
                """INSERT INTO quality_evidence (
                    evidence_id, model_id, task, score, evaluator, source, sample_count,
                    observed_at, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evidence.evidence_id,
                    evidence.model_id,
                    evidence.task,
                    str(evidence.score),
                    evidence.evaluator,
                    evidence.source,
                    evidence.sample_count,
                    _timestamp(evidence.observed_at),
                    _json(evidence.metadata),
                ),
            )
        return evidence

    def list_quality_evidence(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[TaskQualityEvidence]:
        """Return quality evidence in the task-selection API's normalized shape."""
        return [
            _task_quality_evidence(row)
            for row in self.query_quality_evidence(model_id=model_id, task=task)
        ]

    def query_quality_evidence(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[QualityEvidence]:
        filters: builtins.list[str] = []
        values: builtins.list[str] = []
        if model_id is not None:
            filters.append("model_id = ?")
            values.append(model_id)
        if task is not None:
            filters.append("task = ?")
            values.append(task)
        sql = "SELECT * FROM quality_evidence"
        if filters:
            sql += " WHERE " + " AND ".join(filters)
        sql += " ORDER BY observed_at, evidence_id"
        with self._connection() as connection:
            self._ensure_schema(connection)
            rows = connection.execute(sql, values)
            return [_quality_evidence_from_row(row) for row in rows]

    def delete_before(self, timestamp: datetime) -> int:
        cutoff = _timestamp(timestamp)
        with self._transaction() as connection:
            cursor = connection.execute("DELETE FROM observations WHERE timestamp < ?", (cutoff,))
            return cursor.rowcount

    def vacuum(self) -> None:
        with self._lock, self._connection() as connection:
            self._ensure_schema(connection)
            connection.execute("VACUUM")

    def export_jsonl(self) -> str:
        observations = self.query_observations()
        results = self.query_benchmark_results()
        records = [
            _envelope("observation", row.model_dump(mode="python")) for row in observations
        ] + [_envelope("benchmark_result", row.model_dump(mode="python")) for row in results]
        records.sort(
            key=lambda record: (
                record["record_type"],
                _record_sort_key(record["record"]),
            )
        )
        return "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            for record in records
        )

    def import_jsonl(self, content: str, *, deduplicate: bool = False) -> int:
        records: builtins.list[tuple[int, Observation | BenchmarkResult]] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                envelope = json.loads(line)
                if not isinstance(envelope, dict):
                    raise TypeError("JSONL record must be an object")
                schema_version = envelope.get("schema_version")
                if (
                    not isinstance(schema_version, int)
                    or isinstance(schema_version, bool)
                    or schema_version != SCHEMA_VERSION
                ):
                    raise ValueError("unsupported JSONL schema version")
                kind = envelope.get("record_type")
                if kind == "observation":
                    record_data = envelope["record"]
                    if not isinstance(record_data, dict):
                        raise TypeError("observation record must be an object")
                    if "observation_id" not in record_data or "timestamp" not in record_data:
                        raise ValueError("observation record requires observation_id and timestamp")
                    records.append((line_number, Observation.model_validate(record_data)))
                elif kind == "benchmark_result":
                    records.append(
                        (line_number, BenchmarkResult.model_validate(envelope["record"]))
                    )
                else:
                    raise ValueError("unknown record_type")
            except (KeyError, TypeError, ValueError) as exc:
                raise ImportRecordError(
                    f"invalid JSONL record on line {line_number}: {exc}"
                ) from exc

        imported = 0
        seen_observation_ids: set[str] = set()
        seen_result_ids: set[tuple[str, str, str]] = set()
        with self._transaction() as connection:
            for line_number, record in records:
                try:
                    if isinstance(record, Observation):
                        observation_id = record.observation_id
                        duplicate = (
                            observation_id in seen_observation_ids
                            or connection.execute(
                                "SELECT 1 FROM observations WHERE observation_id = ?",
                                (observation_id,),
                            ).fetchone()
                            is not None
                        )
                        if duplicate:
                            if deduplicate:
                                continue
                            raise ValueError("duplicate observation_id")
                        prepared = _apply_payload_policy(record, self.payload_policy)
                        connection.execute(
                            f"INSERT INTO observations ({','.join(_OBSERVATION_COLUMNS)}) "
                            f"VALUES ({','.join('?' for _ in _OBSERVATION_COLUMNS)})",
                            _observation_values(prepared),
                        )
                        seen_observation_ids.add(observation_id)
                    else:
                        result_id = (record.run_id, record.case_id, record.model_id)
                        duplicate = (
                            result_id in seen_result_ids
                            or connection.execute(
                                """SELECT 1 FROM benchmark_results
                            WHERE run_id = ? AND case_id = ? AND model_id = ?""",
                                result_id,
                            ).fetchone()
                            is not None
                        )
                        if duplicate:
                            if deduplicate:
                                continue
                            raise ValueError("duplicate benchmark result identity")
                        connection.execute(
                            """INSERT INTO benchmark_results (
                                run_id, case_id, model_id, score, evaluator, cost, latency_ms,
                                metadata_json
                            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                            _benchmark_result_values(record),
                        )
                        seen_result_ids.add(result_id)
                    imported += 1
                except (sqlite3.IntegrityError, ValueError) as exc:
                    raise ImportRecordError(
                        f"invalid JSONL record on line {line_number}: {exc}"
                    ) from exc
        return imported

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        with self._lock:
            if self.path == ":memory:":
                if self._memory_connection is None:
                    self._memory_connection = sqlite3.connect(
                        self.path, timeout=5, check_same_thread=False
                    )
                    _configure(self._memory_connection)
                yield self._memory_connection
            else:
                path = Path(self.path)
                try:
                    path.parent.mkdir(parents=True, exist_ok=True)
                except OSError as exc:
                    raise ObservationStoreError("storage directory could not be created") from exc
                try:
                    connection = sqlite3.connect(path, timeout=5)
                except sqlite3.Error as exc:
                    raise ObservationStoreError("could not open analytics database") from exc
                try:
                    _configure(connection)
                    yield connection
                finally:
                    connection.close()

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        with self._connection() as connection:
            self._ensure_schema(connection)
            connection.execute("BEGIN IMMEDIATE")
            try:
                yield connection
            except BaseException:
                connection.rollback()
                raise
            else:
                connection.commit()

    @staticmethod
    def _ensure_schema(connection: sqlite3.Connection) -> None:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()
        try:
            version = int(row[0]) if row else 0
        except (TypeError, ValueError) as exc:
            raise ObservationStoreError("database schema version is corrupt") from exc
        if version > SCHEMA_VERSION:
            raise UnsupportedSchemaVersionError(
                f"database schema version {version} is newer than supported version "
                f"{SCHEMA_VERSION}"
            )
        if version < 0:
            raise ObservationStoreError(f"invalid database schema version: {version}")
        if version == 0:
            _create_schema_v2(connection)
            connection.execute(
                "INSERT OR REPLACE INTO metadata (key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            connection.execute(
                "INSERT OR IGNORE INTO metadata (key, value) VALUES ('created_at', ?)",
                (_timestamp(datetime.now(UTC)),),
            )
        elif version == 1:
            _migrate_schema_v1(connection)
            connection.execute(
                "UPDATE metadata SET value = ? WHERE key = 'schema_version'",
                (str(SCHEMA_VERSION),),
            )
        else:
            _ensure_tables(connection)


class ObservationStore(SQLiteObservationStore):
    """Eagerly initialized compatibility facade for the task-selection API."""

    def __init__(self, database: str | Path) -> None:
        super().__init__(database)
        with self._connection() as connection:
            self._ensure_schema(connection)

    def record(self, observation: TaskObservation) -> None:
        try:
            super().record(observation)
        except sqlite3.Error as exc:
            raise ObservationStoreError("database operation failed") from exc


class InMemoryObservationStore:
    """No-persistence implementation used by tests and ephemeral applications."""

    def __init__(self, *, payload_policy: PayloadPolicy = PayloadPolicy.NONE) -> None:
        self.payload_policy = PayloadPolicy(payload_policy)
        self._observations: dict[str, Observation] = {}
        self._runs: dict[str, BenchmarkRun] = {}
        self._results: dict[tuple[str, str, str], BenchmarkResult] = {}
        self._evidence: dict[str, QualityEvidence] = {}
        self._lock = RLock()

    def record_observation(
        self, observation: Observation, *, deduplicate: bool = False
    ) -> Observation:
        self.record_observations([observation], deduplicate=deduplicate)
        return _apply_payload_policy(observation, self.payload_policy)

    def record(self, observation: TaskObservation) -> None:
        """Store a task-selection observation using the in-memory schema."""
        self.record_observation(_stored_observation(observation))

    def list(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[TaskObservation]:
        """Return observations in the task-selection API's normalized shape."""
        return [
            _task_observation(row)
            for row in self.query_observations(model_id=model_id, task=task)
            if row.latency_ms is not None
        ]

    def record_observations(
        self, observations: builtins.list[Observation], *, deduplicate: bool = False
    ) -> int:
        prepared = [_apply_payload_policy(row, self.payload_policy) for row in observations]
        with self._lock:
            ids = [row.observation_id for row in prepared]
            if not deduplicate and (
                len(ids) != len(set(ids)) or set(ids) & self._observations.keys()
            ):
                raise ValueError("observation_id must be unique")
            before = len(self._observations)
            for row in prepared:
                if row.observation_id not in self._observations:
                    self._observations[row.observation_id] = row
            return len(self._observations) - before

    def query_observations(
        self,
        *,
        model_id: str | None = None,
        task: str | None = None,
        endpoint: str | None = None,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        limit: int | None = None,
    ) -> builtins.list[Observation]:
        _, _ = _observation_filters(
            model_id=model_id,
            task=task,
            endpoint=endpoint,
            since=since,
            recent=recent,
            now_utc=now_utc,
            limit=limit,
        )
        cutoff = _utc(since) if since is not None else None
        if recent is not None:
            cutoff = _utc(now_utc or datetime.now(UTC)) - recent
        with self._lock:
            rows = sorted(
                (
                    row
                    for row in self._observations.values()
                    if (model_id is None or row.model_id == model_id)
                    and (task is None or row.task == task)
                    and (endpoint is None or row.endpoint == endpoint)
                    and (cutoff is None or row.timestamp >= cutoff)
                ),
                key=lambda item: (item.timestamp, item.observation_id),
            )
            return rows[:limit] if limit is not None else rows

    def summarize_model(
        self,
        model_id: str,
        *,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        task: str | None = None,
        endpoint: str | None = None,
        min_samples: int = 5,
    ) -> ObservationSummary:
        return summarize_observations(
            self.query_observations(
                model_id=model_id,
                task=task,
                endpoint=endpoint,
                since=since,
                recent=recent,
                now_utc=now_utc,
            ),
            min_samples=min_samples,
        )

    def summarize_task(
        self,
        task: str,
        *,
        model_id: str | None = None,
        since: datetime | None = None,
        recent: timedelta | None = None,
        now_utc: datetime | None = None,
        endpoint: str | None = None,
        min_samples: int = 5,
    ) -> ObservationSummary:
        return summarize_observations(
            self.query_observations(
                model_id=model_id,
                task=task,
                endpoint=endpoint,
                since=since,
                recent=recent,
                now_utc=now_utc,
            ),
            min_samples=min_samples,
        )

    def record_benchmark_run(self, run: BenchmarkRun) -> BenchmarkRun:
        with self._lock:
            if run.run_id in self._runs:
                raise ValueError("run_id must be unique")
            self._runs[run.run_id] = run
        return run

    def query_benchmark_runs(self) -> builtins.list[BenchmarkRun]:
        with self._lock:
            return sorted(self._runs.values(), key=lambda run: run.run_id)

    def record_benchmark_result(self, result: BenchmarkResult) -> BenchmarkResult:
        key = (result.run_id, result.case_id, result.model_id)
        with self._lock:
            if key in self._results:
                raise ValueError("benchmark result key must be unique")
            self._results[key] = result
        return result

    def query_benchmark_results(
        self, *, run_id: str | None = None
    ) -> builtins.list[BenchmarkResult]:
        with self._lock:
            return sorted(
                (
                    result
                    for result in self._results.values()
                    if run_id is None or result.run_id == run_id
                ),
                key=lambda row: (row.run_id, row.case_id, row.model_id),
            )

    def record_quality_evidence(
        self, evidence: QualityEvidence | TaskQualityEvidence
    ) -> QualityEvidence | TaskQualityEvidence:
        if isinstance(evidence, TaskQualityEvidence):
            evidence = _stored_quality_evidence(evidence)
        with self._lock:
            if evidence.evidence_id in self._evidence:
                raise ValueError("evidence_id must be unique")
            self._evidence[evidence.evidence_id] = evidence
        return evidence

    def list_quality_evidence(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[TaskQualityEvidence]:
        """Return quality evidence in the task-selection API's normalized shape."""
        return [
            _task_quality_evidence(row)
            for row in self.query_quality_evidence(model_id=model_id, task=task)
        ]

    def query_quality_evidence(
        self, *, model_id: str | None = None, task: str | None = None
    ) -> builtins.list[QualityEvidence]:
        with self._lock:
            return sorted(
                (
                    evidence
                    for evidence in self._evidence.values()
                    if (model_id is None or evidence.model_id == model_id)
                    and (task is None or evidence.task == task)
                ),
                key=lambda evidence: (evidence.observed_at, evidence.evidence_id),
            )

    def delete_before(self, timestamp: datetime) -> int:
        cutoff = _utc(timestamp)
        with self._lock:
            ids = [key for key, row in self._observations.items() if row.timestamp < cutoff]
            for key in ids:
                del self._observations[key]
            return len(ids)

    def vacuum(self) -> None:
        return

    def export_jsonl(self) -> str:
        records = [
            _envelope("observation", row.model_dump(mode="python"))
            for row in self.query_observations()
        ] + [
            _envelope("benchmark_result", row.model_dump(mode="python"))
            for row in self.query_benchmark_results()
        ]
        records.sort(
            key=lambda record: (
                record["record_type"],
                _record_sort_key(record["record"]),
            )
        )
        return "".join(
            json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False) + "\n"
            for record in records
        )

    def import_jsonl(self, content: str, *, deduplicate: bool = False) -> int:
        records: builtins.list[tuple[int, Observation | BenchmarkResult]] = []
        for line_number, line in enumerate(content.splitlines(), start=1):
            if not line.strip():
                continue
            try:
                envelope = json.loads(line)
                if not isinstance(envelope, dict):
                    raise TypeError("JSONL record must be an object")
                schema_version = envelope.get("schema_version")
                if (
                    not isinstance(schema_version, int)
                    or isinstance(schema_version, bool)
                    or schema_version != SCHEMA_VERSION
                ):
                    raise ValueError("unsupported JSONL schema version")
                if envelope.get("record_type") == "observation":
                    record_data = envelope["record"]
                    if not isinstance(record_data, dict):
                        raise TypeError("observation record must be an object")
                    if "observation_id" not in record_data or "timestamp" not in record_data:
                        raise ValueError("observation record requires observation_id and timestamp")
                    records.append((line_number, Observation.model_validate(record_data)))
                elif envelope.get("record_type") == "benchmark_result":
                    records.append(
                        (line_number, BenchmarkResult.model_validate(envelope["record"]))
                    )
                else:
                    raise ValueError("unknown record_type")
            except (KeyError, TypeError, ValueError) as exc:
                raise ImportRecordError(
                    f"invalid JSONL record on line {line_number}: {exc}"
                ) from exc
        pending_observations: dict[str, Observation] = {}
        pending_results: dict[tuple[str, str, str], BenchmarkResult] = {}
        with self._lock:
            observation_ids = set(self._observations)
            result_ids = set(self._results)
            for line_number, record in records:
                if isinstance(record, Observation):
                    observation_id = record.observation_id
                    if observation_id in observation_ids:
                        if deduplicate:
                            continue
                        raise ImportRecordError(
                            f"invalid JSONL record on line {line_number}: duplicate observation_id"
                        )
                    observation_ids.add(observation_id)
                    pending_observations[observation_id] = _apply_payload_policy(
                        record, self.payload_policy
                    )
                else:
                    result_id = (record.run_id, record.case_id, record.model_id)
                    if result_id in result_ids:
                        if deduplicate:
                            continue
                        raise ImportRecordError(
                            f"invalid JSONL record on line {line_number}: "
                            "duplicate benchmark result identity"
                        )
                    result_ids.add(result_id)
                    pending_results[result_id] = record
            self._observations.update(pending_observations)
            self._results.update(pending_results)
        return len(pending_observations) + len(pending_results)


_OBSERVATION_COLUMNS = (
    "observation_id",
    "timestamp",
    "model_id",
    "endpoint",
    "gateway",
    "provider",
    "task",
    "success",
    "failure_category",
    "input_tokens",
    "output_tokens",
    "cached_read_tokens",
    "cached_write_tokens",
    "reasoning_tokens",
    "estimated_cost",
    "actual_cost",
    "cost_source",
    "latency_ms",
    "time_to_first_token_ms",
    "finish_reason",
    "request_fingerprint",
    "metadata_json",
)


def _configure(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.isolation_level = None
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA foreign_keys = ON")


def _create_schema_v2(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS observations (
            observation_id TEXT PRIMARY KEY,
            timestamp TEXT NOT NULL,
            model_id TEXT NOT NULL,
            endpoint TEXT,
            gateway TEXT,
            provider TEXT,
            task TEXT,
            success INTEGER NOT NULL CHECK (success IN (0, 1)),
            failure_category TEXT,
            input_tokens INTEGER CHECK (input_tokens IS NULL OR input_tokens >= 0),
            output_tokens INTEGER CHECK (output_tokens IS NULL OR output_tokens >= 0),
            cached_read_tokens INTEGER CHECK (
                cached_read_tokens IS NULL OR cached_read_tokens >= 0
            ),
            cached_write_tokens INTEGER CHECK (
                cached_write_tokens IS NULL OR cached_write_tokens >= 0
            ),
            reasoning_tokens INTEGER CHECK (reasoning_tokens IS NULL OR reasoning_tokens >= 0),
            estimated_cost TEXT,
            actual_cost TEXT,
            cost_source TEXT,
            latency_ms TEXT,
            time_to_first_token_ms TEXT,
            finish_reason TEXT,
            request_fingerprint TEXT,
            metadata_json TEXT NOT NULL
        )"""
    )
    _create_payload_table(connection)
    connection.execute(
        """CREATE TABLE IF NOT EXISTS benchmark_runs (
            run_id TEXT PRIMARY KEY,
            dataset_id TEXT NOT NULL,
            dataset_version TEXT,
            dataset_hash TEXT,
            started_at TEXT NOT NULL,
            ended_at TEXT,
            runner_version TEXT,
            configuration_json TEXT NOT NULL,
            status TEXT NOT NULL
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS benchmark_results (
            run_id TEXT NOT NULL,
            case_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            score TEXT,
            evaluator TEXT,
            cost TEXT,
            latency_ms TEXT,
            metadata_json TEXT NOT NULL,
            PRIMARY KEY (run_id, case_id, model_id)
        )"""
    )
    connection.execute(
        """CREATE TABLE IF NOT EXISTS quality_evidence (
            evidence_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            task TEXT,
            score TEXT NOT NULL,
            evaluator TEXT NOT NULL,
            source TEXT NOT NULL,
            sample_count INTEGER NOT NULL CHECK (sample_count > 0),
            observed_at TEXT NOT NULL,
            metadata_json TEXT NOT NULL
        )"""
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS observations_model_time ON observations(model_id, timestamp)"
    )
    connection.execute(
        "CREATE INDEX IF NOT EXISTS observations_task_time ON observations(task, timestamp)"
    )


def _create_payload_table(connection: sqlite3.Connection) -> None:
    connection.execute(
        """CREATE TABLE IF NOT EXISTS observation_payloads (
            observation_id TEXT PRIMARY KEY REFERENCES observations(observation_id)
                ON DELETE CASCADE,
            prompt TEXT,
            response TEXT
        )"""
    )


def _migrate_schema_v1(connection: sqlite3.Connection) -> None:
    _create_payload_table(connection)
    columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)")}
    if {"prompt", "response"} <= columns:
        connection.execute(
            """INSERT INTO observation_payloads (observation_id, prompt, response)
            SELECT observation_id, prompt, response FROM observations
            WHERE prompt IS NOT NULL OR response IS NOT NULL"""
        )
        connection.execute("ALTER TABLE observations DROP COLUMN prompt")
        connection.execute("ALTER TABLE observations DROP COLUMN response")
    _ensure_tables(connection)


def _ensure_tables(connection: sqlite3.Connection) -> None:
    required = {
        "observations",
        "observation_payloads",
        "benchmark_runs",
        "benchmark_results",
        "quality_evidence",
    }
    existing = {
        row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
    }
    if not required <= existing:
        raise ObservationStoreError("database schema is incomplete or corrupt")


def _timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _utc(value).isoformat(timespec="microseconds").replace("+00:00", "Z")


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamps must include a timezone")
    return value.astimezone(UTC)


def _observation_filters(
    *,
    model_id: str | None,
    task: str | None,
    endpoint: str | None,
    since: datetime | None,
    recent: timedelta | None,
    now_utc: datetime | None,
    limit: int | None,
) -> tuple[builtins.list[str], builtins.list[Any]]:
    if since is not None and recent is not None:
        raise ValueError("specify either since or recent, not both")
    if recent is not None and recent.total_seconds() < 0:
        raise ValueError("recent duration must be non-negative")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative")
    filters: builtins.list[str] = []
    values: builtins.list[Any] = []
    for column, value in (("model_id", model_id), ("task", task), ("endpoint", endpoint)):
        if value is not None:
            filters.append(f"{column} = ?")
            values.append(value)
    if since is not None:
        filters.append("timestamp >= ?")
        values.append(_timestamp(since))
    elif recent is not None:
        cutoff = _utc(now_utc or datetime.now(UTC)) - recent
        filters.append("timestamp >= ?")
        values.append(_timestamp(cutoff))
    return filters, values


def _observation_values(row: Observation) -> tuple[Any, ...]:
    return (
        row.observation_id,
        _timestamp(row.timestamp),
        row.model_id,
        row.endpoint,
        row.gateway,
        row.provider,
        row.task,
        int(row.success),
        row.failure_category,
        row.input_tokens,
        row.output_tokens,
        row.cached_read_tokens,
        row.cached_write_tokens,
        row.reasoning_tokens,
        str(row.estimated_cost) if row.estimated_cost is not None else None,
        str(row.actual_cost) if row.actual_cost is not None else None,
        row.cost_source,
        str(row.latency_ms) if row.latency_ms is not None else None,
        str(row.time_to_first_token_ms) if row.time_to_first_token_ms is not None else None,
        row.finish_reason,
        row.request_fingerprint,
        _json(row.metadata),
    )


def _observation_from_row(row: sqlite3.Row) -> Observation:
    data = dict(row)
    data["timestamp"] = datetime.fromisoformat(data["timestamp"].replace("Z", "+00:00"))
    data["success"] = bool(data["success"])
    data["metadata"] = json.loads(data.pop("metadata_json"))
    for key in ("estimated_cost", "actual_cost", "latency_ms", "time_to_first_token_ms"):
        if data[key] is not None:
            data[key] = Decimal(data[key])
    return Observation.model_validate(data)


def _benchmark_result_values(result: BenchmarkResult) -> tuple[Any, ...]:
    return (
        result.run_id,
        result.case_id,
        result.model_id,
        str(result.score) if result.score is not None else None,
        result.evaluator,
        str(result.cost) if result.cost is not None else None,
        str(result.latency_ms) if result.latency_ms is not None else None,
        _json(result.metadata),
    )


def _benchmark_result_from_row(row: sqlite3.Row) -> BenchmarkResult:
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json"))
    for key in ("score", "cost", "latency_ms"):
        if data[key] is not None:
            data[key] = Decimal(data[key])
    return BenchmarkResult.model_validate(data)


def _benchmark_run_from_row(row: sqlite3.Row) -> BenchmarkRun:
    data = dict(row)
    data["started_at"] = datetime.fromisoformat(data["started_at"].replace("Z", "+00:00"))
    if data["ended_at"] is not None:
        data["ended_at"] = datetime.fromisoformat(data["ended_at"].replace("Z", "+00:00"))
    data["configuration"] = json.loads(data.pop("configuration_json"))
    return BenchmarkRun.model_validate(data)


def _quality_evidence_from_row(row: sqlite3.Row) -> QualityEvidence:
    data = dict(row)
    data["score"] = Decimal(data["score"])
    data["observed_at"] = datetime.fromisoformat(data["observed_at"].replace("Z", "+00:00"))
    data["metadata"] = json.loads(data.pop("metadata_json"))
    return QualityEvidence.model_validate(data)


_COMPATIBILITY_METADATA_KEY = "__model_compass_task_selection__"


def _stored_observation(observation: TaskObservation) -> Observation:
    return Observation(
        timestamp=observation.timestamp,
        model_id=observation.model_id,
        endpoint=observation.endpoint_id,
        task=observation.task,
        success=observation.succeeded,
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
        actual_cost=observation.actual_cost_usd,
        latency_ms=Decimal(observation.latency_ms),
        metadata={
            _COMPATIBILITY_METADATA_KEY: {
                "quality_score": str(observation.quality_score)
                if observation.quality_score is not None
                else None,
                "evaluator_type": observation.evaluator_type,
            }
        },
    )


def _task_observation(observation: Observation) -> TaskObservation:
    compatibility_data = observation.metadata.get(_COMPATIBILITY_METADATA_KEY, {})
    quality_score = (
        compatibility_data.get("quality_score") if isinstance(compatibility_data, dict) else None
    )
    evaluator_type = (
        compatibility_data.get("evaluator_type") if isinstance(compatibility_data, dict) else None
    )
    return TaskObservation(
        model_id=observation.model_id,
        task=observation.task or "general",
        timestamp=observation.timestamp,
        endpoint_id=observation.endpoint,
        succeeded=observation.success,
        latency_ms=int(observation.latency_ms or 0),
        actual_cost_usd=observation.actual_cost,
        input_tokens=observation.input_tokens,
        output_tokens=observation.output_tokens,
        quality_score=quality_score,
        evaluator_type=evaluator_type,
    )


def _stored_quality_evidence(evidence: TaskQualityEvidence) -> QualityEvidence:
    return QualityEvidence(
        model_id=evidence.model_id,
        task=evidence.task,
        score=evidence.quality_score,
        evaluator=evidence.evaluator_type,
        source=evidence.source,
        sample_count=evidence.sample_size,
        observed_at=evidence.evaluated_at,
        metadata={"dataset": evidence.dataset} if evidence.dataset is not None else {},
    )


def _task_quality_evidence(evidence: QualityEvidence) -> TaskQualityEvidence:
    return TaskQualityEvidence(
        model_id=evidence.model_id,
        task=evidence.task or "general",
        quality_score=evidence.score,
        sample_size=evidence.sample_count,
        source=evidence.source,
        evaluator_type=evidence.evaluator,
        dataset=evidence.metadata.get("dataset"),
        evaluated_at=evidence.observed_at,
    )


def _apply_payload_policy(row: Observation, policy: PayloadPolicy) -> Observation:
    if policy == PayloadPolicy.FULL:
        return row
    fingerprint = row.request_fingerprint
    if policy == PayloadPolicy.HASH_ONLY and fingerprint is None and row.prompt is not None:
        fingerprint = fingerprint_request(row.prompt)
    return row.model_copy(
        update={"prompt": None, "response": None, "request_fingerprint": fingerprint}
    )


def fingerprint_request(payload: str | bytes) -> str:
    """Return a SHA-256 fingerprint; predictable inputs are not anonymized."""
    content = payload.encode("utf-8") if isinstance(payload, str) else payload
    return hashlib.sha256(content).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(_jsonable(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return _timestamp(value)
    if isinstance(value, dict):
        return {key: _jsonable(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return [_jsonable(item) for item in value]
    return value


def _envelope(record_type: str, record: dict[str, Any]) -> dict[str, Any]:
    return {
        "record_type": record_type,
        "record": _jsonable(record),
        "schema_version": SCHEMA_VERSION,
    }


def _record_sort_key(record: dict[str, Any]) -> tuple[str, ...]:
    if "observation_id" in record:
        return (record["timestamp"], record["observation_id"])
    return (record["run_id"], record["case_id"], record["model_id"])
