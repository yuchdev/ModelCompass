# Model selection

Selection filters candidates against hard requirements before ranking them. It
retains each candidate's eligibility, stable constraint reason codes, evidence,
and missing-data notes in `SelectionResult.assessments`. Set
`raise_on_empty=True` to raise `NoEligibleModelError`; its `reason_counts`
attribute groups the failed constraints. `human_summary()` explains the chosen
candidate, while `explain(model_id)` reports selection, rank, rejection, and
missing-data evidence for an individual candidate.

## Evidence

`MetricEvidence[T]` keeps a measured value attached to its source, exact task,
sample count, observation time, confidence, and notes. `QualityProvider` is a
read-only lookup protocol. `InMemoryQualityProvider` serves caller-supplied
evidence; `BenchmarkQualityProvider` adapts persisted benchmark results. Neither
performs network access. Execution observations supply task-matched latency and
reliability evidence.

Selection reports raw success rate and uses the **Wilson lower confidence
bound** for reliability ranking. For observed rate `p`, sample count `n`, and
normal quantile `z`:

```text
(p + z²/(2n) - z√(p(1-p)/n + z²/(4n²))) / (1 + z²/n)
```

The default `z=1.96` is a two-sided 95% bound. Configure
`SelectionDataPolicy.min_reliability_samples` to choose when evidence is
considered sufficient for reliability ranking. The raw rate, sample count, and
bound remain separately visible. A `MinimumReliability` constraint evaluates
the raw observed success rate; the conservative bound is the `most-reliable`
ranking value.

## Constraints and missing values

Constraints can be composed from `MinimumQuality`,
`MaximumExpectedCost`, `MaximumLatency`, `MinimumReliability`,
`RequiredCapabilities`, `MinimumContext`, `ModelIdAllowBlock`, and
`GatewayProviderAllowBlock` constraint objects. `select_model` and
`analytics.select` also provide keyword arguments for common constraints.
`ConstraintResult.reason_code` is stable and intended for machine consumers.
Missing evidence fails a numeric hard constraint; incomplete candidate
assessments are retained for diagnostics.

Catalog retrieval time and stale-source state are exposed on the selection
result. The assumptions list describes fallback metrics, including the
small-sample latency fallback from p95 to median.
