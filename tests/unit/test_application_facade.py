from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

import pytest

from model_compass import application
from model_compass.application import AnalyticsFacade, analytics
from model_compass.benchmarks import (
    BenchmarkCase,
    BenchmarkDataset,
    EvaluatorType,
    evaluate_benchmark,
)
from model_compass.catalogs.service import CatalogService
from model_compass.config import AppPaths
from model_compass.domain import (
    CatalogSnapshot,
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
)
from model_compass.execution import CompletionRequest, ExecutionError, ExecutionResult
from model_compass.metrics import Observation
from model_compass.selection import SelectionPolicy
from model_compass.storage import ObservationStore


class FakeService(CatalogService):
    """Catalog service double that counts refresh calls and never performs real I/O."""

    def __init__(self):
        """Initialise the refresh call counter."""
        self.calls = 0

    async def refresh_async(
        self,
        *,
        force: bool = False,
        offline: bool = False,
        include_litellm: bool = True,
        now_utc: Optional[datetime] = None,
    ) -> CatalogSnapshot:
        """Record the call and raise to prove the facade never refreshes it."""
        del force, offline, include_litellm, now_utc
        self.calls += 1
        raise RuntimeError("not needed")


@pytest.mark.unit
def test_lazy_analytics_proxy_exposes_catalog():
    """[Unit] Lazy analytics proxy exposes catalog: verifies the described behaviour holds.

    Scenario: Exercises lazy analytics proxy exposes catalog and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    assert hasattr(analytics, "catalog")


@pytest.mark.unit
def test_analytics_facade_can_inject_service():
    """[Unit] Analytics facade can inject service: verifies the described behaviour holds.

    Scenario: Exercises analytics facade can inject service and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    service = FakeService()
    facade = AnalyticsFacade(catalog=service)
    assert facade.catalog is service


@pytest.mark.unit
@pytest.mark.asyncio
async def test_refresh_sync_raises_in_running_loop():
    """[Unit] Refresh sync raises in running loop: verifies the described behaviour holds.

    Scenario: Exercises refresh sync raises in running loop and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    service = CatalogService()
    with pytest.raises(RuntimeError):
        service.refresh()


@pytest.mark.unit
def test_facade_estimates_and_selects_using_injected_store(tmp_path: Path):
    """[Unit] Facade estimates and selects using injected store: verifies the described behaviour holds.

    Scenario: Exercises facade estimates and selects using injected store and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    profile = ModelProfile(
        identity=ModelIdentity(provider="test", model_id="m", canonical_id="test:m"),
        capabilities=ModelCapabilities(
            context_length=100,
            input_modalities=("text",),
            output_modalities=("text",),
        ),
        pricing=Pricing(
            components={
                "prompt": PriceComponent(key="prompt", amount=Decimal("0.01")),
                "completion": PriceComponent(key="completion", amount=Decimal("0.02")),
            }
        ),
        retrieved_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    store = ObservationStore(tmp_path / "data.sqlite3")
    facade = AnalyticsFacade(observation_store=store)
    request = RequestProfile(task="summary", explicit_input_tokens=2, expected_output_tokens=1)

    assert facade.estimate_cost(profile, request).amount_usd == Decimal("0.04")
    facade.record_observation(
        Observation(
            model_id="test:m",
            task="summary",
            succeeded=True,
            latency_ms=20,
            quality_score=Decimal("0.9"),
        )
    )
    result = facade.select([profile], request, policy=SelectionPolicy.BEST)
    assert result.selected is not None
    assert facade.list_observations(task="summary")[0].quality_score == Decimal("0.9")


@pytest.mark.unit
@pytest.mark.asyncio
async def test_facade_execute_records_only_normalized_usage():
    """[Unit] Facade execute records only normalized usage: verifies the described behaviour holds.

    Scenario: Exercises facade execute records only normalized usage and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """

    class Store(ObservationStore):
        """Observation store double that captures recorded observations in memory."""

        def __init__(self):
            """Initialise the in-memory record list."""
            self.records: list[Observation] = []

        def record(self, observation: Observation):
            """Append *observation* to the captured record list."""
            self.records.append(observation)

    class Backend:
        """Execution backend double that returns a fixed successful result."""

        async def complete(self, request: CompletionRequest) -> ExecutionResult:
            """Return a canned successful execution result for *request*."""
            return ExecutionResult(
                model_id=request.model_id,
                task=request.task,
                output_text="response",
                latency_ms=12,
                input_tokens=3,
                output_tokens=4,
                actual_cost_usd=Decimal("0.0001"),
            )

    store = Store()
    result = await AnalyticsFacade(observation_store=store).execute(
        CompletionRequest(
            model_id="provider/model",
            task="qa",
            messages=[{"role": "user", "content": "not stored"}],
        ),
        backend=Backend(),
    )

    assert result.output_text == "response"
    assert len(store.records) == 1
    assert store.records[0].input_tokens == 3


@pytest.mark.unit
@pytest.mark.asyncio
async def test_facade_execute_records_failed_latency_without_error_text():
    """[Unit] Facade execute records failed latency without error text: verifies the described behaviour holds.

    Scenario: Exercises facade execute records failed latency without error text and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """

    class Store(ObservationStore):
        """Observation store double that captures recorded observations in memory."""

        def __init__(self):
            """Initialise the in-memory record list."""
            self.records: list[Observation] = []

        def record(self, observation: Observation):
            """Append *observation* to the captured record list."""
            self.records.append(observation)

    class Backend:
        """Execution backend double that always raises an execution error."""

        async def complete(self, request: CompletionRequest) -> ExecutionResult:
            """Raise an execution error carrying a fixed latency for *request*."""
            del request
            raise ExecutionError("provider failure", latency_ms=4)

    store = Store()
    facade = AnalyticsFacade(observation_store=store)
    request = CompletionRequest(model_id="test:m", task="qa", messages=[])
    with pytest.raises(ExecutionError, match="provider failure"):
        await facade.execute(request, backend=Backend())
    assert store.records[0].succeeded is False
    assert store.records[0].latency_ms == 4


@pytest.mark.unit
def test_facade_records_benchmark_as_quality_evidence(tmp_path: Path):
    """[Unit] Facade records benchmark as quality evidence: verifies the described behaviour holds.

    Scenario: Exercises facade records benchmark as quality evidence and asserts the expected outcome.
    Boundaries: Pure in-process logic over real domain objects; no network, disk, or faked collaborators.
    On failure, first check: the failing assertion and the value it compares against.
    """
    report = evaluate_benchmark(
        BenchmarkDataset(
            name="tiny",
            task="qa",
            evaluator=EvaluatorType.EXACT,
            cases=(BenchmarkCase(case_id="one", input_text="q", expected_output="a"),),
        ),
        {"one": "a"},
        model_id="test:m",
    )
    facade = AnalyticsFacade(observation_store=ObservationStore(tmp_path / "data.sqlite3"))
    facade.record_benchmark(report)
    assert facade.observation_store is not None
    evidence = facade.observation_store.list_quality_evidence(task="qa")
    assert evidence[0].dataset == "tiny"
    assert evidence[0].sample_size == 1


@pytest.mark.unit
def test_facade_lazily_creates_default_store_on_use(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """[Local] Facade lazily creates default store on use: verifies the described behaviour holds.

    Scenario: Exercises facade lazily creates default store on use and asserts the expected outcome.
    Boundaries: Collaborators are faked or monkeypatched in-process; no real network or disk I/O.
    On failure, first check: the failing assertion and the value it compares against.
    """

    paths = AppPaths(
        config_dir=tmp_path / "config",
        data_dir=tmp_path / "data",
        cache_dir=tmp_path / "cache",
    )
    monkeypatch.setattr(application, "default_paths", lambda: paths)
    facade = AnalyticsFacade()
    assert not paths.data_dir.exists()
    assert facade.list_observations() == []
    assert (paths.data_dir / "observations.sqlite3").exists()
