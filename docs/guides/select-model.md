# Select a model

Selection applies hard filters first, then ranks the remaining candidates.

## Cheapest above a quality threshold

```python
from decimal import Decimal

from model_compass import RequestProfile, SelectionPolicy, analytics
from model_compass.selection import InMemoryQualityProvider, MetricEvidence

request = RequestProfile(
    task="summarization",
    explicit_input_tokens=4_000,
    expected_output_tokens=500,
    min_quality=Decimal("0.85"),
    max_cost_usd=Decimal("0.02"),
)
provider = InMemoryQualityProvider(
    {
        "demo:small": MetricEvidence(value=Decimal("0.91"), source="benchmark", task="summarization", sample_count=12),
        "demo:large": MetricEvidence(value=Decimal("0.97"), source="benchmark", task="summarization", sample_count=12),
    }
)
result = analytics.select(profiles, request, policy=SelectionPolicy.CHEAPEST, quality_provider=provider)
print(result.selected.model_id if result.selected else "no eligible model")
```

Hard filters run before ranking, so a model that fails the quality, cost, context, capability, or allow/block checks never reaches the objective ranker.

## Policy notes

- `cheapest` minimizes complete expected cost.
- `best` maximizes task-matched quality.
- `fastest` prefers observed latency, using the documented sample-threshold fallback.
- `most-reliable` uses the Wilson lower confidence bound.
- `cost-efficient` ranks by quality divided by expected cost.

`MissingDataPolicy.REJECT` is the default: unknown values are visible and rejected when they matter to a hard requirement. `MissingDataPolicy.ALLOW` keeps unknowns from turning into hard failures, but it does not invent a metric.
