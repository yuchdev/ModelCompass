# Empirical observations

An `Observation` is one measured model execution, separate from request cost
estimates. It can record a model, endpoint, task, success or failure, token usage,
latency, time to first token, actual cost, estimated cost, and sanitized metadata.
The two cost values stay separate; summaries label the available basis as `actual`,
`estimated`, `mixed`, or `none`.

All timestamps must include a timezone and are normalized to UTC. Latency p50 and
p95 use the **nearest-rank** quantile: sort the available measurements and select
the item at index `ceil(p*n) - 1` for percentile `p`. Means and costs use
`Decimal`, not binary floating-point arithmetic.

Every summary reports its sample counts. By default, each statistic requires five
observations that contain the relevant measurement before exposing rates, means,
quantiles, or totals. Callers can pass a different `min_samples` threshold; below
it, sample counts remain visible and the corresponding derived values are
suppressed. In particular, a success rate from a single request should not be
treated as strong reliability evidence.

## Privacy

`PayloadPolicy.NONE` is the default: prompt and response fields are discarded when
recording. `HASH_ONLY` also discards those fields and stores a SHA-256 request
fingerprint when a prompt is supplied. A cryptographic hash is **not anonymization**:
highly predictable or low-entropy inputs can often be guessed.

`PayloadPolicy.FULL` explicitly opts in to storing raw prompt and response data.
Use it only when the database's access controls, retention, backups, and handling
meet the sensitivity requirements of that data. Metadata is caller-supplied and
must also be reviewed to ensure it does not contain prompts, responses, or secrets.

Benchmark runs and results are stored separately from execution observations.
`QualityEvidence` provides a normalized record for benchmark-derived or imported
quality scores without conflating those scores with runtime success or latency.
