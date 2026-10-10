# 06. Model selection

**Level:** intermediate · **Time:** 25 minutes · **Needs:** [03. Request profiles](03-request-profile.md) and [05. Observations](05-observations.md)

In this tutorial you will learn how selection narrows the field, how it judges evidence, and how to read the explanation it gives back. For hands-on steps, see [the selection guides](../guides/05-select-model.md).

## Step 1: See the two phases

Selection filters candidates against hard requirements before ranking them. It keeps each candidate's eligibility, stable constraint reason codes, evidence, and missing-data notes in `SelectionResult.assessments`.

## Step 2: Ask for an explanation

- `human_summary()` explains the chosen candidate.
- `explain(model_id)` reports selection, rank, rejection, and missing-data evidence for one candidate.
- `raise_on_empty=True` raises `NoEligibleModelError`; its `reason_counts` attribute groups the failed constraints.

## Step 3: Understand evidence

`MetricEvidence[T]` keeps a measured value attached to its source, exact task, sample count, observation time, confidence, and notes.

- `QualityProvider` is a read-only lookup protocol.
- `InMemoryQualityProvider` serves caller-supplied evidence.
- `BenchmarkQualityProvider` adapts persisted benchmark results.
- Neither performs network access.
- Execution observations supply task-matched latency and reliability evidence.

## Step 4: Learn how reliability is scored

Selection reports the raw success rate and ranks reliability by the **Wilson lower confidence bound**. For observed rate `p`, sample count `n`, and normal quantile `z`:

```text
(p + z²/(2n) - z√(p(1-p)/n + z²/(4n²))) / (1 + z²/n)
```

The default `z=1.96` is a two-sided 95% bound. A model with 3 of 3 successes ranks below one with 95 of 100, because the small sample could be luck. Set `SelectionDataPolicy.min_reliability_samples` to choose when evidence is sufficient. The raw rate, sample count, and bound stay separately visible.

A `MinimumReliability` constraint checks the raw observed rate. The conservative bound is the `most-reliable` ranking value.

## Step 5: Compose constraints

Build constraints from `MinimumQuality`, `MaximumExpectedCost`, `MaximumLatency`, `MinimumReliability`, `RequiredCapabilities`, `MinimumContext`, `ModelIdAllowBlock`, and `GatewayProviderAllowBlock`. `select_model` and `analytics.select` also accept keyword arguments for the common ones.

`ConstraintResult.reason_code` is stable and meant for machine consumers. Missing evidence fails a numeric hard constraint, and incomplete assessments are kept for diagnostics.

## Step 6: Check freshness and assumptions

Catalog retrieval time and stale-source state are exposed on the selection result. The assumptions list describes fallback metrics, including the small-sample latency fallback from p95 to median.

## What you learned

- Filter first, rank second.
- Reliability is ranked conservatively.
- Every outcome can be explained by code.

## Next

[07. Pareto analysis](07-pareto.md) shows how to keep tradeoffs instead of picking one winner.
