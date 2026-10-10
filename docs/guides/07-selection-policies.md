# 07. Selection policies

**Level:** intermediate · **Time:** 20 minutes · **Needs:** [05. Select a model](05-select-model.md) and [06. Analytics and selection](06-analytics.md)

In this tutorial you will learn exactly what happens to a model between "candidate" and "winner": why it was rejected, how it was ranked, and how ties and missing data are handled.

## Step 1: Run a constrained selection

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

## Step 2: Find out why a model lost

Hard constraints run before ranking. A rejected model remains in `result.assessments` with machine-readable `ConstraintResult` values and stable reason codes.

If no candidate survives, inspect `result.rejection_counts`. Pass `raise_on_empty=True` to receive a structured `NoEligibleModelError` instead.

## Step 3: Learn the ordering of each policy

All final ties use the canonical model ID, so output is deterministic.

| Policy | Primary objective | Tie-breakers |
|---|---|---|
| `cheapest` | Minimize complete expected request cost | Higher applicable quality, higher conservative reliability, lower latency |
| `best` | Maximize task-matched quality | Lower expected cost, higher conservative reliability, lower latency |
| `fastest` | Minimize p95 observed latency when sample threshold is met | Otherwise use observed median; evidence and sample count are attached |
| `most-reliable` | Maximize Wilson lower confidence bound | Evidence below `min_reliability_samples` ranks after sufficient evidence |
| `cost-efficient` | Maximize `quality / expected_cost` | Canonical ID |

## Step 4: Understand cost-efficiency edge cases

`cost-efficient` requires known quality and a complete cost by default.

- A zero-cost, positive-quality candidate ranks as positive infinity. It serializes with `cost_efficiency_state="positive_infinity"` rather than a non-standard JSON float.
- A zero-cost, zero-quality candidate has no defined ratio and is not rankable.
- The policy is a transparent heuristic, not an optimality guarantee.

## Step 5: Understand missing data

- Unknown values sort after known values for tie-breakers and are preserved in assessments.
- `cheapest` requires a complete expected cost; `fastest` requires latency evidence by default; `most-reliable` requires observed success evidence.
- Missing values fail a hard numeric constraint by default.

`compare_models` applies its `missing_data_policy` to both its capability eligibility report and every policy ranking. With `MissingDataPolicy.ALLOW`:

- Unknown capability and threshold evidence does not become a second strict selection constraint.
- Candidates can still be unrankable when the policy's primary objective itself needs unavailable data.
- A known partial cost above a maximum cost limit is still rejected.

## Step 6: Trust the numbers shown

Comparison ranks use the same per-model token and cost estimates shown on each candidate. When a prompt or messages tokenize differently for different models, cost-based ranks reflect those model-specific estimates. A cost-based rank is available whenever the displayed estimate is complete.

Quality providers and observations are task-specific, and no external leaderboard is fetched during selection. Use `MetricEvidence` to inspect source, task, count, timestamp, confidence, and notes for each empirical metric.

## What you learned

- How to read `assessments` and `rejection_counts`.
- The primary objective and tie-breakers of every policy.
- How missing data is rejected, ranked last, or allowed.

## Next

[08. Local storage](08-storage.md) explains where observations live and how to protect them.
