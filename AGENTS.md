# Agent Execution Contract

This file defines the execution contract for GitHub Copilot coding agents working on this repository.

## Before Making Changes

1. Read this file, the master specification in the problem statement, the assigned issue, `README.md`, and relevant architecture docs.
2. Inspect existing code before designing new APIs. Do not duplicate concepts already implemented.
3. Implement only the assigned issue plus minimal compatibility changes required by it.
4. Preserve public API compatibility unless the issue explicitly changes it.

## Quality Commands (must all pass)

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
uv run mkdocs build --strict
uv build
```

## Architectural Dependency Rules

```
domain <- catalogs
domain <- metrics
domain <- selection
domain <- storage
domain <- execution
cli    -> public application/service API
```

The domain layer must NOT import: LiteLLM, Typer, Rich, HTTPX, SQLite, or provider SDKs.

## Test Categories

| Marker | Description |
|--------|-------------|
| `unit` | No network, no external services, one class/function in isolation |
| `mock` | HTTP mocked with respx, LiteLLM calls mocked |
| `integration` | Multi-component, temp SQLite, real CLI invocation |
| `live` | External APIs, opt-in only, skipped without credentials |
| `slow` | Long-running tests |

## Prohibitions

- Do NOT weaken Ruff, MyPy, pytest, or coverage configuration to make checks pass.
- Do NOT leave placeholder implementations, `pass`, fake data, or TODOs for acceptance criteria.
- Do NOT make mandatory tests depend on internet access or secrets.
- Do NOT persist API keys or log secrets.
- Do NOT add global `ignore_missing_imports = true` to mypy config.
- Do NOT use binary floats for price/cost calculations (use `decimal.Decimal`).
- Do NOT create directories at import time.

## Implementation Rules

1. Do not leave placeholder implementations, `pass`, fake data, or TODOs for acceptance criteria.
2. Never make mandatory tests depend on internet access or secrets.
3. Add tests alongside every non-trivial code path.
4. Add/update user and developer documentation when public behavior changes.
5. Run all required quality gates before finishing.
6. If a documented external API differs from the implementation encountered during live testing, preserve the raw payload, update the adapter defensively, add a regression fixture/test, and document the discrepancy.
7. Do not silently weaken quality checks.
8. Summary of work in PR description: files changed, design decisions, tests added, commands run, remaining risks.
