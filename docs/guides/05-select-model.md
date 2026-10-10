# 05. Select a model

**Level:** intermediate · **Time:** 15 minutes · **Needs:** [04. Compare models](04-compare-models.md)

Comparison shows every candidate. Selection picks one. In this tutorial you will pick the cheapest model that clears a quality bar, then see how the five policies differ.

Selection applies hard filters first, then ranks whatever survives.

## Step 1: Describe the request with hard limits

```python
from decimal import Decimal

from model_compass import RequestProfile, SelectionPolicy, analytics

request = RequestProfile(
    task="summarization",
    explicit_input_tokens=4_000,
    expected_output_tokens=500,
    min_quality=Decimal("0.85"),
    max_cost_usd=Decimal("0.02"),
)
```

## Step 2: Supply quality evidence

A quality threshold is only meaningful if there is evidence to check it against. `InMemoryQualityProvider` holds task-specific scores.

```python
from model_compass.selection import InMemoryQualityProvider, MetricEvidence

provider = InMemoryQualityProvider(
    {
        "demo:small": MetricEvidence(value=Decimal("0.91"), source="benchmark", task="summarization", sample_count=12),
        "demo:large": MetricEvidence(value=Decimal("0.97"), source="benchmark", task="summarization", sample_count=12),
    }
)
```

## Step 3: Select

```python
result = analytics.select(profiles, request, policy=SelectionPolicy.CHEAPEST, quality_provider=provider)
print(result.selected.model_id if result.selected else "no eligible model")
```

A model that fails the quality, cost, context, capability, or allow/block checks never reaches the ranker.

## Step 4: Try the other policies

Change `policy=` and run again to see how the answer moves:

- `cheapest` minimizes complete expected cost.
- `best` maximizes task-matched quality.
- `fastest` prefers observed latency, using the documented sample-threshold fallback.
- `most-reliable` uses the Wilson lower confidence bound.
- `cost-efficient` ranks by quality divided by expected cost.

## Step 5: Decide how to treat missing data

`MissingDataPolicy.REJECT` is the default: unknown values are visible and rejected when they matter to a hard requirement. `MissingDataPolicy.ALLOW` keeps unknowns from turning into hard failures, but it does not invent a metric.

## What you learned

- That filters run before ranking.
- That quality thresholds need matching evidence.
- That unknown data is rejected by default.

## Next

[06. Analytics and selection](06-analytics.md) covers richer requests and recording what actually happened.
