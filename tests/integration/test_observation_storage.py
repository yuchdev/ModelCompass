from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from model_compass.application import AnalyticsFacade
from model_compass.domain import (
    BenchmarkResult,
    BenchmarkRun,
    Observation,
    PayloadPolicy,
    QualityEvidence,
)
from model_compass.storage import (
    ImportRecordError,
    InMemoryObservationStore,
    ObservationStoreError,
    SQLiteObservationStore,
    UnsupportedSchemaVersionError,
)


def _observation(
    observation_id: str,
    *,
    timestamp: datetime | None = None,
    prompt: str | None = None,
    response: str | None = None,
    actual_cost: Decimal | None = None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        timestamp=timestamp or datetime(2026, 1, 1, tzinfo=UTC),
        model_id="provider:model",
        endpoint="https://gateway.example/v1",
        task="summarization",
        success=True,
        prompt=prompt,
        response=response,
        actual_cost=actual_cost,
        latency_ms=Decimal("125.5"),
        metadata={"region": "test"},
    )


@pytest.mark.integration
def test_sqlite_create_reopen_query_and_lazy_initialization(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "observations.db"
    store = SQLiteObservationStore(path)
    facade = AnalyticsFacade(observation_store=store)

    assert facade.observation_store is store
    assert not path.exists()

    store.record_observation(_observation("one", actual_cost=Decimal("0.03")))
    reopened = SQLiteObservationStore(path)
    rows = reopened.query_observations(
        model_id="provider:model",
        task="summarization",
        endpoint="https://gateway.example/v1",
        since=datetime(2025, 12, 31, tzinfo=UTC),
    )
    assert rows[0].actual_cost == Decimal("0.03")
    assert rows[0].prompt is None
    assert facade.summarize_model(
        "provider:model", min_samples=1
    ).cost.total_actual_cost == Decimal("0.03")


@pytest.mark.integration
def test_memory_store_contract_time_windows_and_summaries() -> None:
    store = InMemoryObservationStore()
    store.record_observation(_observation("old"))
    store.record_observation(_observation("recent", timestamp=datetime(2026, 1, 2, tzinfo=UTC)))

    result = store.query_observations(
        recent=timedelta(days=1),
        now_utc=datetime(2026, 1, 2, 12, tzinfo=UTC),
    )
    assert [row.observation_id for row in result] == ["recent"]
    assert store.summarize_task("summarization").reliability.success_count == 2
    with pytest.raises(ValueError, match="either since or recent"):
        store.query_observations(since=datetime(2026, 1, 1, tzinfo=UTC), recent=timedelta(days=1))


@pytest.mark.integration
def test_sqlite_memory_bulk_deduplication_filters_deletion_and_vacuum() -> None:
    store = SQLiteObservationStore(":memory:")
    first = _observation("first")
    second = _observation("second", timestamp=datetime(2026, 1, 2, tzinfo=UTC))

    assert store.record_observations([]) == 0
    assert store.record_observations([first, second]) == 2
    assert store.record_observations([first], deduplicate=True) == 0
    assert store.query_observations(limit=1) == [first]
    assert store.query_observations(
        recent=timedelta(days=1), now_utc=datetime(2026, 1, 2, 12, tzinfo=UTC)
    ) == [second]
    assert store.summarize_task("summarization", min_samples=1).reliability.sample_count == 2
    assert (
        store.summarize_model(
            "provider:model",
            recent=timedelta(days=1),
            now_utc=datetime(2026, 1, 2, 12, tzinfo=UTC),
            min_samples=1,
        ).reliability.sample_count
        == 1
    )
    assert store.query_benchmark_results(run_id="missing") == []
    assert store.delete_before(datetime(2026, 1, 2, tzinfo=UTC)) == 1
    assert [row.observation_id for row in store.query_observations()] == ["second"]
    store.vacuum()


@pytest.mark.integration
def test_sqlite_bulk_write_rolls_back_on_failure(tmp_path: Path) -> None:
    store = SQLiteObservationStore(tmp_path / "observations.db")
    with pytest.raises(sqlite3.IntegrityError):
        store.record_observations([_observation("duplicate"), _observation("duplicate")])
    assert store.query_observations() == []


@pytest.mark.integration
def test_multiple_sqlite_connections_can_write_sequentially(tmp_path: Path) -> None:
    path = tmp_path / "observations.db"
    first = SQLiteObservationStore(path)
    second = SQLiteObservationStore(path)
    first.record_observation(_observation("first"))
    second.record_observation(_observation("second"))
    assert len(first.query_observations()) == 2


@pytest.mark.integration
def test_version_zero_migrates_and_future_schema_is_rejected(tmp_path: Path) -> None:
    legacy_path = tmp_path / "legacy.db"
    with sqlite3.connect(legacy_path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '0')")
    migrated = SQLiteObservationStore(legacy_path)
    assert migrated.query_observations() == []
    with sqlite3.connect(legacy_path) as connection:
        version = connection.execute(
            "SELECT value FROM metadata WHERE key = 'schema_version'"
        ).fetchone()[0]
    assert version == "1"

    unsupported_path = tmp_path / "future.db"
    with sqlite3.connect(unsupported_path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '999')")
    with pytest.raises(UnsupportedSchemaVersionError):
        SQLiteObservationStore(unsupported_path).query_observations()

    corrupt_path = tmp_path / "corrupt.db"
    with sqlite3.connect(corrupt_path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', 'invalid')")
    with pytest.raises(ObservationStoreError, match="corrupt"):
        SQLiteObservationStore(corrupt_path).query_observations()

    incomplete_path = tmp_path / "incomplete.db"
    with sqlite3.connect(incomplete_path) as connection:
        connection.execute("CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        connection.execute("INSERT INTO metadata (key, value) VALUES ('schema_version', '1')")
    with pytest.raises(ObservationStoreError, match="incomplete"):
        SQLiteObservationStore(incomplete_path).query_observations()


@pytest.mark.integration
def test_export_import_round_trip_and_bad_line_number(tmp_path: Path) -> None:
    source = SQLiteObservationStore(tmp_path / "source.db")
    source.record_observation(
        _observation("one", prompt="secret text", actual_cost=Decimal("0.0000001"))
    )
    source.record_benchmark_run(
        BenchmarkRun(
            run_id="run-1",
            dataset_id="dataset",
            started_at=datetime(2026, 1, 1, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, 1, tzinfo=UTC),
            status="complete",
        )
    )
    source.record_benchmark_result(
        BenchmarkResult(
            run_id="run-1",
            case_id="case-1",
            model_id="provider:model",
            score=Decimal("0.875"),
            cost=Decimal("0.01"),
        )
    )
    exported = source.export_jsonl()
    assert exported == source.export_jsonl()
    actual_cost = json.loads(exported.splitlines()[-1])["record"]["actual_cost"]
    assert Decimal(actual_cost) == Decimal("0.0000001")
    assert "secret text" not in exported

    restored = SQLiteObservationStore(tmp_path / "restored.db")
    assert restored.import_jsonl(exported) == 2
    assert restored.export_jsonl() == exported
    assert restored.import_jsonl(exported, deduplicate=True) == 0
    with pytest.raises(ImportRecordError, match="line 1"):
        restored.import_jsonl('{"schema_version":1,"record_type":"unknown","record":{}}\n')
    with pytest.raises(ImportRecordError, match="schema version"):
        restored.import_jsonl('{"schema_version":true,"record_type":"observation","record":{}}\n')

    assert restored.query_benchmark_runs() == []


@pytest.mark.integration
def test_benchmark_run_and_quality_evidence_are_persisted(tmp_path: Path) -> None:
    store = SQLiteObservationStore(tmp_path / "evidence.db")
    run = BenchmarkRun(
        run_id="run",
        dataset_id="dataset-v1",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        status="complete",
        configuration={"seed": 10},
    )
    evidence = QualityEvidence(
        evidence_id="quality",
        model_id="provider:model",
        task="summarization",
        score=Decimal("0.8"),
        evaluator="judge-v1",
        source="benchmark",
    )
    store.record_benchmark_run(run)
    store.record_quality_evidence(evidence)
    assert store.query_benchmark_runs() == [run]
    assert store.query_quality_evidence(model_id="provider:model") == [evidence]
    assert store.query_quality_evidence(task="summarization") == [evidence]


@pytest.mark.integration
def test_import_reports_line_number_and_rolls_back_prior_records(tmp_path: Path) -> None:
    source = InMemoryObservationStore()
    source.record_observation(_observation("one"))
    record = source.export_jsonl().strip()
    store = SQLiteObservationStore(tmp_path / "rollback.db")
    with pytest.raises(ImportRecordError, match="line 2"):
        store.import_jsonl(f"{record}\n{record}\n")
    assert store.query_observations() == []


@pytest.mark.integration
def test_memory_backend_deduplication_and_benchmark_records() -> None:
    store = InMemoryObservationStore()
    row = _observation("row")
    assert store.record_observations([]) == 0
    assert store.record_observations([row, row], deduplicate=True) == 1
    with pytest.raises(ValueError, match="unique"):
        store.record_observations([row])
    run = BenchmarkRun(
        run_id="memory-run",
        dataset_id="dataset",
        started_at=datetime(2026, 1, 1, tzinfo=UTC),
        status="complete",
    )
    store.record_benchmark_run(run)
    with pytest.raises(ValueError, match="run_id"):
        store.record_benchmark_run(run)
    result = BenchmarkResult(
        run_id="memory-run",
        case_id="case",
        model_id="provider:model",
        score=Decimal("0.5"),
    )
    store.record_benchmark_result(result)
    with pytest.raises(ValueError, match="benchmark result"):
        store.record_benchmark_result(result)
    evidence = QualityEvidence(
        evidence_id="memory-evidence",
        model_id="provider:model",
        score=Decimal("0.7"),
        evaluator="judge",
        source="import",
    )
    store.record_quality_evidence(evidence)
    with pytest.raises(ValueError, match="evidence_id"):
        store.record_quality_evidence(evidence)
    assert store.query_benchmark_runs() == [run]
    assert store.query_benchmark_results(run_id="memory-run") == [result]
    assert store.query_quality_evidence(model_id="provider:model") == [evidence]
    assert store.delete_before(datetime(2026, 1, 2, tzinfo=UTC)) == 1
    store.vacuum()


@pytest.mark.integration
def test_application_construction_does_not_create_default_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from model_compass import config

    monkeypatch.setattr(config, "user_data_dir", lambda *args: str(tmp_path / "data"))
    AnalyticsFacade()
    assert not (tmp_path / "data").exists()


@pytest.mark.integration
def test_payload_policy_hashes_or_explicitly_persists_prompt(tmp_path: Path) -> None:
    raw = _observation("payload", prompt="sensitive", response="sensitive response")
    hash_store = SQLiteObservationStore(
        tmp_path / "hash.db", payload_policy=PayloadPolicy.HASH_ONLY
    )
    hashed = hash_store.record_observation(raw)
    assert hashed.request_fingerprint is not None
    assert len(hashed.request_fingerprint) == 64
    assert hash_store.query_observations()[0].prompt is None

    full_store = SQLiteObservationStore(tmp_path / "full.db", payload_policy=PayloadPolicy.FULL)
    full_store.record_observation(raw)
    assert full_store.query_observations()[0].prompt == "sensitive"
    assert full_store.query_observations()[0].response == "sensitive response"
