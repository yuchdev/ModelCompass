# 05. Empirical observations

**Level:** intermediate · **Time:** 15 minutes · **Needs:** [04. Cost estimation](04-cost-estimation.md)

Estimates are predictions. Observations are measurements. In this tutorial you will learn what an observation holds, how summaries are computed, and how to keep sensitive data out of storage.

## Step 1: Know what an observation records

An `Observation` is one measured model execution, separate from request cost estimates. It can record a model, endpoint, task, success or failure, token usage, latency, time to first token, actual cost, estimated cost, and sanitized metadata.

The two cost values stay separate. Summaries label the available basis as `actual`, `estimated`, `mixed`, or `none`.

## Step 2: Mind the timestamps and statistics

All timestamps must include a timezone and are normalized to UTC. Latency p50 and p95 use the **nearest-rank** quantile: sort the available measurements and take the item at index `ceil(p*n) - 1` for percentile `p`. Means and costs use `Decimal`, not binary floating-point arithmetic.

## Step 3: Respect the sample threshold

Every summary reports its sample counts. By default, each statistic needs five observations containing the relevant measurement before it exposes rates, means, quantiles, or totals. Pass a different `min_samples` to change this. Below the threshold, sample counts stay visible and the derived values are suppressed.

A success rate from a single request is not strong reliability evidence.

## Step 4: Choose a payload policy

- `PayloadPolicy.NONE` is the default. Prompt and response fields are discarded when recording.
- `HASH_ONLY` also discards them and stores a SHA-256 request fingerprint when a prompt is supplied. A cryptographic hash is **not anonymization**: predictable or low-entropy inputs can often be guessed.
- `PayloadPolicy.FULL` explicitly opts in to storing raw prompt and response data. Use it only when the database's access controls, retention, and backups meet the sensitivity of that data.

Metadata is caller-supplied. Review it to make sure it holds no prompts, responses, or secrets.

## Step 5: Keep benchmarks separate

Benchmark runs and results are stored separately from execution observations. `QualityEvidence` records benchmark-derived or imported quality scores without mixing them with runtime success or latency.

## What you learned

- Observations hold measurements; estimates stay separate.
- Statistics are suppressed below the sample threshold.
- Payloads are not stored unless you opt in.

## Next

[06. Selection](06-selection.md) uses observations as evidence to pick a model.
