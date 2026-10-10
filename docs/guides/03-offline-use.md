# 03. Offline use

**Level:** beginner · **Time:** 10 minutes · **Needs:** [02. Catalogs](02-catalogs.md) (one prior refresh)

Model Compass can run without live provider access if you stick to cached catalog data, in-memory profiles, and offline benchmark scoring. In this tutorial you will go through each part and learn which parts can never be offline.

## Step 1: Use the cached catalog

Run a refresh once while online, then add `--offline` to catalog-backed commands. This requires the cached OpenRouter snapshot instead of fetching live data.

```bash
uv run model-compass catalog refresh --source openrouter --offline
uv run model-compass models list --offline --limit 5
```

## Step 2: Select and compare with profiles you already have

Selection and comparison only need profiles in memory, from the cache or built by hand as in [01. Quickstart](01-quickstart.md).

```python
from model_compass import RequestProfile, SelectionPolicy, analytics

request = RequestProfile(task="qa", explicit_input_tokens=1_000, expected_output_tokens=200)
result = analytics.select(profiles, request, policy=SelectionPolicy.CHEAPEST)
```

## Step 3: Score benchmarks without a backend

`evaluate_offline()` scores pre-collected outputs against a single-task dataset without calling a model. [10. Benchmarks](10-benchmarks.md) explains the dataset format.

## Step 4: Know what cannot be offline

Execution is live by design. To try it without a provider key, use the example scripts, which run against a fake backend.

## Step 5: Run the example scripts

- `examples/list_models.py`
- `examples/estimate_cost.py`
- `examples/compare_models.py`
- `examples/constrained_selection.py`
- `examples/pareto_frontier.py`
- `examples/benchmark_fake_backend.py`

`examples/execute_with_litellm.py` is a dry run by default and explains how to opt into a real call.

## What you learned

- That `--offline` means "cache only, never fetch".
- That selection, comparison, and benchmark scoring work with no network.
- That only execution needs a live provider.

## Next

[04. Compare models](04-compare-models.md) puts several candidates side by side.
