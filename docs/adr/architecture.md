# Architecture

## Component Diagram

```text
Application / CLI
        |
        v
+----------------------------+
| Model Analytics            |
|----------------------------|
| Request profile            |
| Capability constraints     |
| Pricing / cost estimates   |
| Quality evidence           |
| Reliability / latency      |
| Selection policies         |
| Pareto analysis            |
| Explanation                |
+----------------------------+
        |
        +-----------------------------+
        |                             |
        v                             v
+--------------------+       +----------------------+
| Catalog adapters   |       | Execution backends   |
|--------------------|       |----------------------|
| OpenRouter live    |       | LiteLLM (primary)    |
| LiteLLM metadata   |       | future backends      |
| snapshots/imports  |       +----------------------+
+--------------------+
        |
        v
+----------------------------+
| Observation / benchmark DB |
| SQLite                     |
+----------------------------+
```

## Dependency Rules

```text
domain <- catalogs
domain <- metrics
domain <- selection
domain <- storage
domain <- execution
cli    -> public application/service API
```

The domain layer must not import LiteLLM, Typer, Rich, HTTPX, SQLite, or provider SDKs.

## Key Design Decisions

- All money values use `decimal.Decimal`
- Platform paths via `platformdirs` — no directories created at import time
- Public exceptions derive from `ModelAnalyticsError`
- Capabilities use tri-state: SUPPORTED / UNSUPPORTED / UNKNOWN
- Missing data never makes a model satisfy a hard positive requirement
