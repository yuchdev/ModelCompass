# Architecture

```text
CLI / application facade
          |
          v
request profiles -> cost / selection / Pareto -> explanations
       |                    |                     |
       v                    v                     v
catalog adapters      empirical metrics      SQLite observations
OpenRouter/LiteLLM    benchmarks              execution
```

The dependency direction is domain-first: catalogs, metrics, selection,
storage, and execution depend on provider-independent domain objects. The
domain package does not import HTTPX, LiteLLM, Typer, Rich, SQLite, or provider
SDKs. The CLI calls the public application facade for stored observations and
selection.

## Boundaries

- `domain`: normalized profiles, price components, request requirements, and
  missing-data policy.
- `catalogs`: OpenRouter HTTP/cache adapter, LiteLLM metadata adapter, and
  deterministic merge.
- `selection`: Decimal cost estimation, capability filtering, ranking policies,
  explanations, and Pareto analysis.
- `metrics` / `storage`: typed, prompt-free observations and task-specific
  summaries backed by SQLite.
- `execution`: LiteLLM completion adapter with normalized latency/token/cost
  usage.
- `benchmarks`: deterministic offline exact, regex, and JSON evaluators.

No network calls or directories are created merely by importing the package.
Directories for the SQLite store are created only when the store is first used.
