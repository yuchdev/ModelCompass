from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from model_compass.exceptions import StorageError
from model_compass.metrics import Observation, QualityEvidence
from model_compass.storage import ObservationStore


@pytest.mark.integration
def test_observation_store_round_trips_exact_values_and_filters(tmp_path: Path):
    """[Integration] exact round trip: stored values and filters return observations unchanged.

    Scenario: Records an observation and quality evidence, queries with filters, inspects the schema.
    Boundaries: Real SQLite ObservationStore on the temp filesystem; schema read via sqlite3.
    On failure, first check: exact Decimal/int persistence and that payload columns are absent.
    """
    store = ObservationStore(tmp_path / "nested" / "observations.sqlite3")
    item = Observation(
        model_id="openrouter:provider/model",
        task="summarization",
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        succeeded=True,
        latency_ms=42,
        actual_cost_usd=Decimal("0.000000123"),
        input_tokens=100,
        output_tokens=20,
        quality_score=Decimal("0.975"),
    )

    store.record(item)
    assert store.list() == [item]
    assert store.list(model_id=item.model_id) == [item]
    assert store.list(task="other") == []

    with sqlite3.connect(tmp_path / "nested" / "observations.sqlite3") as connection:
        columns = {row[1] for row in connection.execute("PRAGMA table_info(observations)")}
    assert "prompt" not in columns
    assert "messages" not in columns

    evidence = QualityEvidence(
        model_id=item.model_id,
        task=item.task,
        quality_score=Decimal("0.9"),
        sample_size=10,
        source="benchmark",
        evaluator_type="exact",
        dataset="sample",
    )
    store.record_quality_evidence(evidence)
    assert store.list_quality_evidence(task=item.task) == [evidence]
    assert store.list_quality_evidence(model_id="other") == []


@pytest.mark.integration
def test_observation_store_wraps_database_errors(tmp_path: Path):
    """[Integration] db errors wrapped: open and write failures surface as StorageError.

    Scenario: Opens a store on a directory path, then forces an insert failure via a reject trigger.
    Boundaries: Real SQLite ObservationStore on the temp filesystem; trigger added via sqlite3.
    On failure, first check: sqlite exceptions being wrapped into StorageError with stable messages.
    """
    with pytest.raises(StorageError, match="could not open"):
        ObservationStore(tmp_path)

    store = ObservationStore(tmp_path / "observations.sqlite3")

    with sqlite3.connect(tmp_path / "observations.sqlite3") as connection:
        connection.execute(
            """
            CREATE TRIGGER reject_observation BEFORE INSERT ON observations
            BEGIN SELECT RAISE(ABORT, 'rejected'); END
            """
        )
    observation = Observation(
        model_id="test:model",
        task="qa",
        succeeded=True,
        latency_ms=1,
    )
    with pytest.raises(StorageError, match="database operation failed"):
        store.record(observation)
    assert store.list() == []


@pytest.mark.integration
def test_observation_store_wraps_directory_creation_errors(tmp_path: Path):
    """[Integration] dir creation error: a non-directory parent path surfaces as StorageError.

    Scenario: Places a file where a directory is expected, then opens a store beneath it.
    Boundaries: Real ObservationStore and filesystem; no mocks.
    On failure, first check: directory-creation failures being wrapped into StorageError.
    """
    blocker = tmp_path / "file"
    blocker.write_text("not a directory")
    with pytest.raises(StorageError, match="storage directory"):
        ObservationStore(blocker / "observations.sqlite3")
