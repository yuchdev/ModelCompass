from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest

from model_compass.exceptions import StorageError
from model_compass.metrics import Observation, QualityEvidence
from model_compass.storage import ObservationStore


@pytest.mark.integration
def test_observation_store_round_trips_exact_values_and_filters(tmp_path: Path) -> None:
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

    import sqlite3

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
def test_observation_store_wraps_database_errors(tmp_path: Path) -> None:
    with pytest.raises(StorageError, match="could not open"):
        ObservationStore(tmp_path)

    store = ObservationStore(tmp_path / "observations.sqlite3")
    import sqlite3

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
