from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from model_compass.catalogs import OpenRouterCatalogAdapter
from model_compass.domain import RequestProfile
from model_compass.metrics import FallbackTokenEstimator
from model_compass.selection import ComparisonReport, compare_models, workload_scenario

FIXTURE_DIR = Path(__file__).parents[1] / "fixtures" / "catalogs"


@pytest.mark.integration
@pytest.mark.asyncio
async def test_offline_catalog_cache_can_be_compared_and_round_tripped(
    tmp_path: Path,
) -> None:
    now = datetime(2026, 1, 1, tzinfo=UTC)
    source_adapter = OpenRouterCatalogAdapter(cache_dir=tmp_path)
    payload = json.loads(
        (FIXTURE_DIR / "openrouter_ordinary_text.json").read_text(encoding="utf-8")
    )
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
def test_catalog_request_to_cost_comparison_for_synthetic_scenario() -> None:
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
