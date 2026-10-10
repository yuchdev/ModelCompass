# 08. Quality evidence

**Level:** advanced · **Time:** 30 minutes · **Needs:** [06. Selection](06-selection.md) and [the benchmarks guide](../guides/10-benchmarks.md)

In this tutorial you will follow a quality score from its source to the moment selection trusts it, and learn what each step does not claim.

Quality is never one universal number. `model_compass.benchmarks` produces
**task-scoped** quality evidence, and selection never averages across
unrelated tasks without an explicit, caller-supplied weighting.

## Step 1: Find where evidence comes from

Three independent sources feed the same evidence shape
(`model_compass.domain.QualityEvidence` for storage,
`model_compass.metrics.task_observations.QualityEvidence` for selection):

1. **Local benchmarks** — `run_benchmark` executes a `BenchmarkDataset`
   against real or fake models, producing `BenchmarkResult` rows, which
   `benchmarks.aggregation.summarize_quality` turns into task-, dataset-, or
   tag-scoped `QualitySummary` objects. `QualitySummary.to_quality_evidence()`
   converts a summary into persistable evidence with `source="benchmark"`.
2. **Offline scoring** — `benchmarks.evaluate_offline` scores pre-collected
   string outputs against a single-task dataset without an execution backend
   (used by `model-compass benchmark` on the CLI). It also produces
   `source="benchmark"` evidence.
3. **Imported evidence** — `benchmarks.import_external_evidence` normalizes
   externally reported scores (leaderboards, vendor reports) into the same
   shape, tagged `source="imported:<original source>"`. Scores are normalized
   only when their scale is known (`0-1`, `0-100`, `percentage`); an unknown
   scale is never guessed at, and the import either raises or skips the
   record per the caller's choice.

## Step 2: Resolve evidence for a request

`model_compass.selection.evidence.resolve_quality_evidence` (and its
`QualityProvider` adapter, `TieredQualityProvider`) applies an explicit,
traceable precedence:

1. **Exact-task local benchmark evidence** (`QualityResolutionRule.EXACT_TASK_LOCAL_BENCHMARK`).
2. **Exact-task imported evidence** (`EXACT_TASK_IMPORTED_BENCHMARK`), only
   used when no local evidence exists for that exact task.
3. **Broader fallback evidence** (`BROADER_FALLBACK`) — any task, local and
   imported combined — **only** when the caller passes `allow_fallback=True`.
   This is never automatic.
4. Otherwise `None`: quality is unknown for that model and task, and
   selection treats it as missing data rather than guessing a value.

The resolved `MetricEvidence.resolution_rule` field records which tier
produced the answer, so a selection result can always explain *why* it
trusted (or distrusted) a given quality number.
`selection.evidence.partition_quality_evidence` splits a mixed list of
evidence (e.g. everything returned by
`ObservationStore.list_quality_evidence`) into local and imported buckets
using the `source` naming convention above.

## Step 3: Aggregate and measure confidence

`summarize_quality` groups scored cases by model and by one dimension at a
time: `task`, `dataset`, `tag`, or `overall`. `overall` **requires** an
explicit `weights` mapping from task name to weight; a task present in the
data but missing from `weights` raises, so a "global quality" number can
never silently blend unrelated tasks.

Each `QualitySummary` carries `mean_score`, `median_score`, an optional
`pass_rate` (only meaningful when the underlying evaluator records a
pass/fail verdict), `sample_count`, and an optional `confidence_interval`.
Confidence intervals use a deterministic bootstrap: `scores` are resampled
with replacement under a seeded `random.Random`, so the same scores and seed
always produce the same interval
(`model_compass.benchmarks.bootstrap_confidence_interval`). This is a
standard, dependency-free method — not a claim of exact sampling-theory
guarantees, and it requires at least two scores.

## Step 4: Know the limits

- No benchmark result claims bit-for-bit LLM reproducibility; see
  `docs/guides/10-benchmarks.md` for what *is* recorded for reproducibility.
- Budget controls on live runs are conservative estimates, not a guarantee —
  see the "Budget safety" section of `docs/guides/10-benchmarks.md`.
- The optional LLM judge is opt-in, never silently invoked, and is
  documented separately in `docs/guides/11-custom-evaluators.md`, including its
  known bias and non-independence limitations.

## What you learned

- Three sources feed one evidence shape.
- Resolution follows a fixed, recorded precedence and never falls back unless you allow it.
- `overall` quality needs explicit weights.

## Next

[09. Execution](09-execution.md) covers how real calls produce the observations behind this evidence.
