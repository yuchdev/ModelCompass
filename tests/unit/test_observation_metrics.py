from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest
from hypothesis import given
from hypothesis import strategies as st

from model_compass.domain import BenchmarkRun, Observation, QualityEvidence
from model_compass.metrics import summarize_observations
from model_compass.storage import InMemoryObservationStore, fingerprint_request


def _observation(
    observation_id: str,
    *,
    success: bool = True,
    latency: str | None = None,
    actual: str | None = None,
    estimated: str | None = None,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
) -> Observation:
    return Observation(
        observation_id=observation_id,
        timestamp=datetime(2026, 1, 1, tzinfo=UTC),
        model_id="provider:model",
        task="summarization",
        success=success,
        failure_category=None if success else "timeout",
        latency_ms=Decimal(latency) if latency is not None else None,
        actual_cost=Decimal(actual) if actual is not None else None,
        estimated_cost=Decimal(estimated) if estimated is not None else None,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


@pytest.mark.unit
def test_summary_uses_nearest_rank_quantiles_and_keeps_cost_sources_separate() -> None:
    summary = summarize_observations(
        [
            _observation(
                "1", latency="1", actual="0.12", estimated="0.15", input_tokens=10, output_tokens=4
            ),
            _observation("2", success=False, latency="2", estimated="0.25", input_tokens=20),
            _observation("3", latency="3", actual="0.30", output_tokens=8),
            _observation("4", latency="4", input_tokens=30, output_tokens=12),
        ],
        min_samples=1,
    )

    assert summary.latency.p50_latency_ms == Decimal("2")
    assert summary.latency.p95_latency_ms == Decimal("4")
    assert summary.latency.mean_latency_ms == Decimal("2.5")
    assert summary.reliability.success_count == 3
    assert summary.reliability.success_rate == Decimal("0.75")
    assert summary.cost.cost_basis == "mixed"
    assert summary.cost.total_actual_cost == Decimal("0.42")
    assert summary.cost.total_estimated_cost == Decimal("0.40")
    assert summary.usage.average_input_tokens == Decimal("20")
    assert summary.usage.average_output_tokens == Decimal("8")


@pytest.mark.unit
def test_minimum_sample_suppresses_rates_and_estimates() -> None:
    summary = summarize_observations(
        [_observation("only", success=False, latency="50", actual="1")],
        min_samples=2,
    )

    assert summary.sufficient_samples is False
    assert summary.reliability.sample_count == 1
    assert summary.reliability.success_rate is None
    assert summary.latency.p50_latency_ms is None
    assert summary.cost.total_actual_cost is None


@pytest.mark.unit
def test_minimum_sample_threshold_applies_to_each_metric_denominator() -> None:
    rows = [_observation(str(index)) for index in range(5)]
    rows[0] = _observation("0", latency="20", actual="0.1", input_tokens=8)
    summary = summarize_observations(rows)

    assert summary.reliability.success_rate == Decimal(1)
    assert summary.latency.latency_sample_count == 1
    assert summary.latency.p50_latency_ms is None
    assert summary.cost.actual_cost_count == 1
    assert summary.cost.total_actual_cost is None
    assert summary.usage.input_token_sample_count == 1
    assert summary.usage.average_input_tokens is None


@pytest.mark.unit
@pytest.mark.parametrize(
    ("actual", "estimated", "expected"),
    [
        ("0.1", None, "actual"),
        (None, "0.1", "estimated"),
        (None, None, "none"),
    ],
)
def test_cost_summary_source_semantics(
    actual: str | None,
    estimated: str | None,
    expected: str,
) -> None:
    summary = summarize_observations(
        [_observation("cost", actual=actual, estimated=estimated)],
        min_samples=1,
    )
    assert summary.cost.cost_basis == expected


@pytest.mark.unit
def test_empty_and_invalid_sample_threshold() -> None:
    empty = summarize_observations([])
    assert empty.reliability.success_rate is None
    assert empty.cost.cost_basis == "none"
    with pytest.raises(ValueError, match="min_samples"):
        summarize_observations([], min_samples=0)


@pytest.mark.unit
def test_timestamp_must_be_aware_and_is_normalized_to_utc() -> None:
    with pytest.raises(ValueError, match="timezone"):
        Observation(
            observation_id="naive",
            timestamp=datetime.fromisoformat("2026-01-01T00:00:00"),
            model_id="provider:model",
            success=True,
        )
    value = Observation(
        observation_id="utc",
        timestamp=datetime.fromisoformat("2026-01-01T02:00:00+02:00"),
        model_id="provider:model",
        success=True,
    )
    assert value.timestamp == datetime(2026, 1, 1, tzinfo=UTC)


@pytest.mark.unit
def test_measurements_are_validated_and_benchmark_times_are_ordered() -> None:
    with pytest.raises(ValueError, match="greater than or equal"):
        Observation(model_id="provider:model", success=True, input_tokens=-1)
    with pytest.raises(ValueError, match="finite"):
        Observation(
            model_id="provider:model",
            success=True,
            actual_cost=Decimal("Infinity"),
        )
    with pytest.raises(ValueError, match="precede"):
        BenchmarkRun(
            run_id="invalid",
            dataset_id="dataset",
            started_at=datetime(2026, 1, 2, tzinfo=UTC),
            ended_at=datetime(2026, 1, 1, tzinfo=UTC),
            status="failed",
        )
    with pytest.raises(ValueError, match="finite"):
        QualityEvidence(
            model_id="provider:model",
            score=Decimal("NaN"),
            evaluator="judge",
            source="benchmark",
        )


@pytest.mark.unit
def test_fingerprint_is_sha256_and_memory_store_defaults_to_no_payload() -> None:
    raw_prompt = "predictable input"
    assert fingerprint_request(raw_prompt) == (
        "5856e97a1c81c8786740ed019f92972165c6c999a7da00db07114f8a744dfe79"
    )
    store = InMemoryObservationStore()
    stored = store.record_observation(
        Observation(
            observation_id="private",
            model_id="provider:model",
            success=True,
            prompt=raw_prompt,
            response="private output",
        )
    )
    assert stored.prompt is None
    assert stored.response is None
    assert store.query_observations()[0].prompt is None
    assert fingerprint_request(b"bytes") == fingerprint_request("bytes")


@given(
    latencies=st.lists(
        st.decimals(min_value=0, max_value=10000, allow_nan=False, allow_infinity=False, places=2),
        min_size=1,
        max_size=20,
    ),
    successes=st.lists(st.booleans(), min_size=1, max_size=20),
)
@pytest.mark.unit
def test_percentiles_and_success_rate_stay_within_bounds(
    latencies: list[Decimal], successes: list[bool]
) -> None:
    size = min(len(latencies), len(successes))
    rows = [
        Observation(model_id="m", success=successes[index], latency_ms=latencies[index])
        for index in range(size)
    ]
    summary = summarize_observations(rows, min_samples=1)
    p50 = summary.latency.p50_latency_ms
    p95 = summary.latency.p95_latency_ms
    success_rate = summary.reliability.success_rate
    assert p50 is not None
    assert p95 is not None
    assert success_rate is not None
    assert min(latencies[:size]) <= p50 <= max(latencies[:size])
    assert min(latencies[:size]) <= p95 <= max(latencies[:size])
    assert Decimal(0) <= success_rate <= Decimal(1)


@given(
    actual=st.lists(
        st.decimals(min_value=0, max_value=100, allow_nan=False, allow_infinity=False, places=4),
        max_size=12,
    )
)
@pytest.mark.unit
def test_actual_cost_totals_equal_the_sum_of_observations(actual: list[Decimal]) -> None:
    rows = [
        Observation(
            model_id="provider:model",
            success=True,
            actual_cost=cost,
        )
        for cost in actual
    ]
    summary = summarize_observations(rows, min_samples=1)
    expected = sum(actual, Decimal(0)) if actual else None
    assert summary.cost.total_actual_cost == expected


@given(
    amount=st.decimals(min_value=0, max_value=100, allow_nan=False, allow_infinity=False, places=6),
    success=st.booleans(),
)
@pytest.mark.unit
def test_jsonl_serialization_round_trip(amount: Decimal, success: bool) -> None:
    store = InMemoryObservationStore()
    store.record_observation(
        Observation(
            observation_id="round-trip",
            timestamp=datetime(2026, 1, 1, 1, tzinfo=UTC),
            model_id="provider:model",
            success=success,
            actual_cost=amount,
        )
    )
    restored = InMemoryObservationStore()
    restored.import_jsonl(store.export_jsonl())
    assert restored.query_observations() == store.query_observations()
