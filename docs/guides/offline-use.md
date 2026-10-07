# Offline use

Model Compass can run without live provider access when you keep to cached catalog data, synthetic profiles, and offline benchmark evaluation.

## Catalogs

Use `--offline` on catalog-backed CLI commands when you want to require the cached OpenRouter snapshot instead of fetching live data.

```bash
uv run model-compass catalog refresh --source openrouter --offline
uv run model-compass models list --offline --limit 5
```

## Selection and comparison

Selection and comparison can be run entirely offline when you already have model profiles in memory or loaded from a cache.

```python
from model_compass import RequestProfile, SelectionPolicy, analytics

request = RequestProfile(task='qa', explicit_input_tokens=1_000, expected_output_tokens=200)
result = analytics.select(profiles, request, policy=SelectionPolicy.CHEAPEST)
```

## Benchmarks

`evaluate_offline()` scores pre-collected outputs against a single-task dataset without a backend. It is the offline path for benchmark scoring.

## Execution

Execution is live by design. If you need a documented offline example, use the example scripts and the fake backend instead of a real provider key.

## Example scripts

- `examples/list_models.py`
- `examples/estimate_cost.py`
- `examples/compare_models.py`
- `examples/constrained_selection.py`
- `examples/pareto_frontier.py`
- `examples/benchmark_fake_backend.py`

The `examples/execute_with_litellm.py` script stays dry-run by default and explains how to opt into a real call.
