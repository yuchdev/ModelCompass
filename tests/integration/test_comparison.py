from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from model_compass.catalogs import OpenRouterCatalogAdapter
from model_compass.domain import RequestProfile
from model_compass.metrics import FallbackTokenEstimator
from model_compass.metrics.task_observations import Observation, QualityEvidence
from model_compass.selection import (
    ComparisonReport,
    SelectionPolicy,
    compare_models,
    workload_scenario,
)

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "catalogs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_offline_catalog_cache_can_be_compared_and_round_tripped(
    tmp_path: Path,
):
    """[Integration] offline compare round trip: a cached catalog compares and serializes losslessly.

    Scenario: Writes a cache from a fixture, reads it offline, compares models and round-trips JSON.
    Boundaries: Real adapter, cache dir and comparison engine; fixture payload and a fallback estimator.
    On failure, first check: offline cache reuse and ComparisonReport JSON serialization equality.
    """
    now = datetime(2026, 1, 1, tzinfo=UTC)
    source_adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    payload = json.loads((FIXTURE_DIR / "openrouter_ordinary_text.json").read_text(encoding="utf-8"))
    snapshot = source_adapter._parse_payload(payload, clock=now)
    source_adapter._write_cache(snapshot=snapshot, raw_payload=payload)

    offline_adapter = OpenRouterCatalogAdapter(
        cache_dir=tmp_path,
        ttl=timedelta(hours=2),
    )
    cached = await offline_adapter.refresh(offline=True, now_utc=now + timedelta(minutes=1))
    report = compare_models(
        list(cached.models.values()),
        RequestProfile(explicit_input_tokens=100, expected_output_tokens=20),
        FallbackTokenEstimator(),
    )

    assert len(report.candidates) == 1
    assert report.candidates[0].cost.complete is True
    restored = ComparisonReport.model_validate_json(report.to_json())
    assert restored == report
    assert restored.to_json() == report.to_json()


@pytest.mark.integration
def test_catalog_request_to_cost_comparison_for_synthetic_scenario():
    """[Integration] request to cost: a synthetic request produces token and cost estimates per model.

    Scenario: Parses a modalities fixture and compares it against a balanced workload request.
    Boundaries: Real adapter parsing, comparison engine and fallback estimator; fixture payload.
    On failure, first check: token-estimate passthrough and the eligibility result for the scenario.
    """
    profile = RequestProfile(
        task="balanced",
        explicit_input_tokens=2048,
        expected_output_tokens=512,
        minimum_context=2560,
    )
    scenario = workload_scenario("balanced")
    catalog_adapter = OpenRouterCatalogAdapter()
    snapshot = catalog_adapter._parse_payload(
        json.loads((FIXTURE_DIR / "openrouter_modalities.json").read_text(encoding="utf-8")),
        clock=datetime(2026, 1, 1, tzinfo=UTC),
    )
    report = compare_models(
        list(snapshot.models.values()),
        profile,
        FallbackTokenEstimator(),
    )

    assert report.candidates[0].token_estimate.input_tokens == 2048
    assert report.candidates[0].cost.complete is True
    assert report.candidates[0].eligibility.eligible is False
    assert scenario.profile.explicit_input_tokens == 2048


@pytest.mark.integration
def test_comparison_includes_policy_ranks_evidence_constraints_and_pareto():
    """[Integration] full comparison: ranks, evidence, constraints and pareto flags are computed.

    Scenario: Compares two models with observations and quality evidence under the BEST policy.
    Boundaries: Real comparison engine and fallback estimator over fixture-derived profiles.
    On failure, first check: per-policy ranks, attached evidence, and pareto membership on candidates.
    """
    catalog_adapter = OpenRouterCatalogAdapter()
    snapshot = catalog_adapter._parse_payload(
        json.loads((FIXTURE_DIR / "openrouter_ordinary_text.json").read_text(encoding="utf-8")),
        clock=datetime(2026, 1, 1, tzinfo=UTC),
    )
    original = next(iter(snapshot.models.values()))
    alternative = original.model_copy(
        update={
            "identity": original.identity.model_copy(
                update={
                    "provider": "test",
                    "model_id": "alternative",
                    "canonical_id": "test:alternative",
                }
            )
        }
    )
    request = RequestProfile(task="task", explicit_input_tokens=100, expected_output_tokens=20)
    observations = [
        Observation(
            model_id=model_id,
            task="task",
            succeeded=index < success_count,
            latency_ms=latency,
        )
        for model_id, success_count, latency in (
            (original.identity.canonical_id, 4, 10),
            ("test:alternative", 5, 20),
        )
        for index in range(5)
    ]
    quality = [
        QualityEvidence(
            model_id=model_id,
            task="task",
            quality_score=score,
            sample_size=5,
            source="synthetic",
            evaluator_type="exact",
        )
        for model_id, score in (
            (original.identity.canonical_id, Decimal("0.8")),
            ("test:alternative", Decimal("0.9")),
        )
    ]
    report = compare_models(
        [original, alternative],
        request,
        FallbackTokenEstimator(),
        observations=observations,
        quality_evidence=quality,
        selected_policy=SelectionPolicy.BEST,
    )

    assert report.selected_policy == SelectionPolicy.BEST
    assert len(report.candidates) == 2
    assert all(
        set(candidate.rank_by_policy) == {policy.value for policy in SelectionPolicy} for candidate in report.candidates
    )
    alternative_report = next(
        candidate for candidate in report.candidates if candidate.model.identity.provider == "test"
    )
    assert alternative_report.quality_evidence is not None
    assert alternative_report.quality_evidence.value == Decimal("0.9")
    assert alternative_report.reliability_evidence is not None
    assert alternative_report.reliability_evidence.sample_count == 5
    assert alternative_report.reliability_evidence.observed_at is not None
    assert alternative_report.rank_by_policy["best"] == 1
    assert alternative_report.pareto_member is True
    restored = ComparisonReport.model_validate_json(report.to_json())
    assert restored == report
