from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

import pytest

from model_compass.metrics.task_observations import QualityEvidence
from model_compass.selection.evidence import (
    QualityResolutionRule,
    TieredQualityProvider,
    partition_quality_evidence,
    resolve_quality_evidence,
)


def _evidence(**overrides: object) -> QualityEvidence:
    """Build a minimal task-shape QualityEvidence, overriding selected fields."""
    defaults: dict[str, object] = {
        "model_id": "test:model",
        "task": "qa",
        "quality_score": Decimal("0.8"),
        "sample_size": 10,
        "source": "benchmark",
        "evaluator_type": "exact@1.0.0",
        "evaluated_at": datetime(2026, 1, 1, tzinfo=UTC),
    }
    defaults.update(overrides)
    return QualityEvidence.model_validate(defaults)


@pytest.mark.unit
def test_resolution_prefers_exact_task_local_over_imported_and_fallback():
    """[Unit] resolution precedence: exact-task local benchmark evidence wins over all else.

    Scenario: Supplies local, imported, and fallback-eligible evidence for the same model/task.
    Boundaries: Pure in-memory resolution logic; no I/O.
    On failure, first check: resolve_quality_evidence's tier ordering.
    """
    local = _evidence(quality_score=Decimal("0.9"), source="benchmark")
    imported = _evidence(quality_score=Decimal("0.1"), source="imported:leaderboard")
    result = resolve_quality_evidence(
        "test:model", "qa", local_benchmark_evidence=[local], imported_evidence=[imported]
    )
    assert result is not None
    assert result.resolution_rule == QualityResolutionRule.EXACT_TASK_LOCAL_BENCHMARK
    assert result.value == Decimal("0.9")


@pytest.mark.unit
def test_resolution_falls_back_to_imported_when_no_local_evidence():
    """[Unit] resolution precedence: imported evidence is used when local evidence is absent.

    Scenario: Supplies only exact-task imported evidence for the model.
    Boundaries: Pure in-memory resolution logic; no I/O.
    On failure, first check: resolve_quality_evidence's second tier.
    """
    imported = _evidence(quality_score=Decimal("0.4"), source="imported:leaderboard")
    result = resolve_quality_evidence("test:model", "qa", imported_evidence=[imported])
    assert result is not None
    assert result.resolution_rule == QualityResolutionRule.EXACT_TASK_IMPORTED_BENCHMARK
    assert result.value == Decimal("0.4")


@pytest.mark.unit
def test_resolution_never_falls_back_without_explicit_opt_in():
    """[Unit] fallback opt-in: broader evidence is ignored unless allow_fallback is True.

    Scenario: Supplies only other-task evidence for the model, first without then with fallback.
    Boundaries: Pure in-memory resolution logic; no I/O.
    On failure, first check: resolve_quality_evidence's allow_fallback guard.
    """
    other_task = _evidence(task="summarization", quality_score=Decimal("0.6"))
    assert resolve_quality_evidence("test:model", "qa", local_benchmark_evidence=[other_task]) is None

    result = resolve_quality_evidence("test:model", "qa", local_benchmark_evidence=[other_task], allow_fallback=True)
    assert result is not None
    assert result.resolution_rule == QualityResolutionRule.BROADER_FALLBACK
    assert result.task is None


@pytest.mark.unit
def test_resolution_returns_none_when_nothing_matches():
    """[Unit] unknown quality: resolution returns None, never a guessed value.

    Scenario: Supplies evidence for a different model entirely.
    Boundaries: Pure in-memory resolution logic; no I/O.
    On failure, first check: resolve_quality_evidence returning None for a non-match.
    """
    assert (
        resolve_quality_evidence("test:model", "qa", local_benchmark_evidence=[_evidence(model_id="other:model")])
        is None
    )


@pytest.mark.unit
def test_tiered_quality_provider_matches_resolve_quality_evidence():
    """[Unit] provider adapter: TieredQualityProvider delegates to resolve_quality_evidence.

    Scenario: Builds a provider with local evidence and queries it through the QualityProvider protocol.
    Boundaries: Pure in-memory resolution logic; no I/O.
    On failure, first check: TieredQualityProvider.get_quality_evidence's delegation.
    """
    provider = TieredQualityProvider(local_benchmark_evidence=[_evidence()])
    result = provider.get_quality_evidence("test:model", "qa")
    assert result is not None
    assert result.resolution_rule == QualityResolutionRule.EXACT_TASK_LOCAL_BENCHMARK


@pytest.mark.unit
def test_partition_quality_evidence_splits_by_source_convention():
    """[Unit] evidence partitioning: splits a mixed list by the imported: source prefix.

    Scenario: Partitions a list containing both benchmark and imported-sourced evidence.
    Boundaries: Pure in-memory logic; no I/O.
    On failure, first check: partition_quality_evidence's source prefix check.
    """
    local = _evidence(source="benchmark")
    imported = _evidence(source="imported:leaderboard")
    local_result, imported_result = partition_quality_evidence([local, imported])
    assert local_result == (local,)
    assert imported_result == (imported,)
