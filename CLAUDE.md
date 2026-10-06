# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

Model Compass is an alpha-stage Python 3.11+ library and CLI (`model-compass`) for request-aware LLM model analytics: catalog ingestion (OpenRouter + LiteLLM), capability matching, token/cost estimation, and model comparison. Quality/latency ranking, storage, execution, and benchmarks packages are still empty stubs. `AGENTS.md` is the authoritative agent contract — read it before non-trivial changes.

## Commands

Uses `uv` (`uv sync --all-groups` to install). All of these quality gates must pass (same as CI):

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests            # strict mode, tests included
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
uv run mkdocs build --strict
uv build --out-dir .dist
```

Running a subset of tests:

```bash
uv run pytest tests/unit/test_catalog_merge.py::test_name   # single test
uv run pytest -m unit                                        # by marker
uv run pytest -m live                                        # opt-in, needs OPENROUTER_API_KEY etc.
```

`--strict-markers` is on: every test must carry one of the registered markers (`unit`, `mock`, `integration`, `live`, `slow`), and the test's directory under `tests/` matches its category. HTTP is mocked with `respx`; OpenRouter payload fixtures live in `tests/fixtures/catalogs/`.

## Architecture

Layered package under `src/model_compass/` with enforced dependency direction:

```
domain <- catalogs | metrics | selection | storage | execution
cli    -> public application/service API
```

`domain/` (pydantic models only) must NOT import LiteLLM, Typer, Rich, HTTPX, SQLite, or provider SDKs.

Data flow:

1. **Catalogs** — `OpenRouterCatalogAdapter` (HTTP via httpx, raw-payload JSON cache in the platform cache dir, 6h TTL, offline mode, falls back to a stale-marked cache on fetch failure) and `LiteLLMCatalogAdapter` (LiteLLM's bundled metadata) both implement the `CatalogProvider` protocol and emit a `CatalogSnapshot`. `merge_catalog_snapshots` combines them deterministically: OpenRouter is primary and wins conflicts *unless its value is UNKNOWN*; conflicts are recorded in `CatalogMergeResult.conflicts`. `CatalogService` orchestrates this and exposes sync (`refresh`, raises inside a running loop) and async (`refresh_async`) entry points.
2. **Domain** — `ModelProfile` is the normalized aggregate (identity, endpoints, capabilities, pricing, provenance). Canonical IDs are `provider:model_id`. `RequestProfile` / `build_request_profile` describe a request and infer its modalities.
3. **Metrics** — `TokenEstimator` protocol with `LiteLLMTokenEstimator` and a character-based `FallbackTokenEstimator`; `estimate_cost` produces per-component `CostEstimate`s from `Pricing`.
4. **Selection** — `check_eligibility` (with `MissingDataPolicy`), named/custom `WorkloadScenario`s, and `compare_models` → `ComparisonReport`.
5. **Application** — `application.analytics` is a lazily constructed `AnalyticsFacade` (avoids side effects at import). The CLI (`cli/app.py`, Typer + Rich) currently only has `version` and `doctor`.

## Invariants to preserve

- Money is always `decimal.Decimal` (use `domain.parse_decimal`), never float.
- Capabilities are tri-state `SupportStatus` (SUPPORTED / UNSUPPORTED / UNKNOWN). Missing source fields stay UNKNOWN, and missing data must never satisfy a hard positive requirement.
- Unknown pricing keys from providers are preserved, not dropped.
- No directories created at import time; paths come from `config.default_paths()` (platformdirs). Directories are created only when writing (e.g. cache writes).
- Public exceptions derive from `ModelCompassError`.
- Pass `now_utc` through for deterministic time in tests rather than patching the clock.
- Don't weaken ruff/mypy/coverage config, add global `ignore_missing_imports`, or leave placeholders/TODOs. Mandatory tests must not need network or secrets.
- If live OpenRouter behavior differs from the docs: keep the raw payload, make the adapter defensive, and add a regression fixture + test.
- Update `docs/` (mkdocs, built with `--strict`) when public behavior changes. Use conventional commits (`feat:`, `fix:`, …).
