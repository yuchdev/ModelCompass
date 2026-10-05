# Selection policies

Build a request with token estimates and hard requirements, then select from
normalized profiles:

```python
from decimal import Decimal

from model_compass import RequestProfile, SelectionPolicy, analytics

request = RequestProfile(
    task="code_review",
    explicit_input_tokens=40_000,
    expected_output_tokens=2_000,
)
result = analytics.select(
    profiles,
    request,
    policy=SelectionPolicy.CHEAPEST,
    min_quality=Decimal("0.90"),
    max_latency_ms=5_000,
)
```

Hard constraints run before ranking. A rejected model remains in
`result.assessments` with machine-readable `ConstraintResult` values and stable
reason codes. If no candidate survives, inspect `result.rejection_counts`; pass
`raise_on_empty=True` to receive a structured `NoEligibleModelError`.

## Policy ordering

All final ties use canonical model ID for deterministic output.

| Policy | Primary objective | Tie-breakers |
|---|---|---|
| `cheapest` | Minimize complete expected request cost | Higher applicable quality, higher conservative reliability, lower latency |
| `best` | Maximize task-matched quality | Lower expected cost, higher conservative reliability, lower latency |
| `fastest` | Minimize p95 observed latency when sample threshold is met | Otherwise use observed median; evidence and sample count are attached |
| `most-reliable` | Maximize Wilson lower confidence bound | Evidence below `min_reliability_samples` ranks after sufficient evidence |
| `cost-efficient` | Maximize `quality / expected_cost` | Canonical ID |

Cost-efficient requires known quality and a complete cost by default. A
zero-cost positive-quality candidate ranks as positive infinity and serializes
with `cost_efficiency_state="positive_infinity"` rather than a non-standard JSON
float. A zero-cost zero-quality candidate has no defined ratio and is not
rankable. This policy is a transparent heuristic, not an optimality guarantee.

Unknown values sort after known values for tie-breakers and are preserved in
assessments. Cheapest requires a complete expected cost; fastest requires
latency evidence by default; most-reliable requires observed success evidence.
Missing values fail a hard numeric constraint. Quality providers
and observations are task-specific; no external leaderboard is fetched during
selection. Use `MetricEvidence` to inspect source, task, count, timestamp,
confidence, and notes for each empirical metric.
