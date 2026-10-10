# 10. Benchmarks

**Level:** advanced · **Time:** 40 minutes · **Needs:** [08. Local storage](08-storage.md) and [09. Executing with LiteLLM](09-litellm.md)

In this tutorial you will build a small dataset, run it against models under a budget, aggregate the scores, and feed them into selection. Steps 1 to 3 need no API key.

`model_compass.benchmarks` runs deterministic, reproducible benchmarks
against any `ExecutionBackend` and turns the results into task-scoped quality
evidence consumed by selection. See `docs/concepts/08-quality.md` for how that
evidence is resolved, and `docs/guides/11-custom-evaluators.md` for writing new
evaluators or using the optional LLM judge.

## Step 1: Build a dataset

A dataset is a JSONL file: one optional header record
(`record_type: "dataset"`, carrying `name`, `version`, and an optional
`description`) followed by one record per case
(`record_type: "case"`). Every case carries a `schema_version`, `case_id`,
`task`, either `messages` or `input_text`, `tags`, `requirements`, an
`evaluator` id, an evaluator-specific expectation, and free-form `metadata`.

```python
from model_compass.benchmarks import BenchmarkCase, BenchmarkDataset, dump_dataset_jsonl, load_dataset_jsonl

dataset = BenchmarkDataset(
    name="geography-smoke",
    version="1.0.0",
    cases=(
        BenchmarkCase(
            case_id="capital-of-france",
            task="qa",
            input_text="What is the capital of France?",
            evaluator="exact",
            expected_output="Paris",
        ),
    ),
)
text = dump_dataset_jsonl(dataset)
reloaded = load_dataset_jsonl(text)
assert reloaded == dataset
```

`BenchmarkCase` is a frozen pydantic model, so a loaded dataset cannot be
mutated during a run — there is no hidden mutation to worry about.

### Check the dataset identity

`dataset.identity` returns a `DatasetIdentity` with `name`, `version`, and a
`content_hash`: a SHA-256 hash computed over the dataset's cases,
**independent of case order**, so identical content always hashes
identically. The hash is a computed property, never a stored field, so it
can never drift from the cases it describes. `BenchmarkRun.dataset_hash`
records this hash for every run, so you can tell whether a dataset changed
between two runs even if its name and version string did not.

See `examples/benchmarks/sample.jsonl` for a worked example covering every built-in evaluator. The legacy `sample-dataset.jsonl` file remains in the tree for compatibility with older docs and tests.

## Step 2: Run a benchmark

```python
from model_compass.benchmarks import BenchmarkRunConfig, RunnerBudget, run_benchmark
from model_compass.execution import LiteLLMBackend

outcome = await run_benchmark(
    dataset,
    ["openrouter/some-model", "openrouter/other-model"],
    backend=LiteLLMBackend(),
    config=BenchmarkRunConfig(
        repetitions=3,
        concurrency=4,
        budget=RunnerBudget(max_total_cost=Decimal("1.00"), max_cases=200),
    ),
)
```

`outcome.run` is a `model_compass.domain.BenchmarkRun` (reproducibility
metadata); `outcome.results` is a tuple of `model_compass.domain.BenchmarkResult`
(one per case/model/repetition); `outcome.scored_cases` pairs each result
with its originating `BenchmarkCase`, ready for
`benchmarks.summarize_quality`.

Before Issue 06 landed, tests used a fake backend
(`tests/fixtures/fake_execution_backend.py`); the same `run_benchmark` call
works unchanged against the real `LiteLLMBackend`.

### Know what happens when a case fails

A failed execution, a failed evaluation, or a budget-exhausted skip produces
its own `BenchmarkResult` with `score=None` and a `metadata["error_category"]`
(`"execution_error"`, `"evaluation_failed"`, `"budget_exceeded"`, or, as a
last-resort net for a genuinely unexpected bug, `"unexpected_error"`) —
**it never discards results already produced by other cases**. No raw
response is persisted by default; set
`BenchmarkRunConfig(persist_raw_responses=True)` to opt in.

Resume semantics (continuing a partially completed run later) are not
implemented in this version. Because every `BenchmarkResult` is independently
persistable, a caller that wants resumability can persist results
incrementally via `ObservationStore.record_benchmark_result` as they arrive,
rather than waiting for the whole run to finish.

## Step 3: Check what was recorded

Every `BenchmarkRun` records: `dataset_id` (the dataset's name), `dataset_version`,
`dataset_hash`, `started_at`/`ended_at`, `runner_version` (this package's
version), and a `configuration` dict (models, repetitions, concurrency, seed,
`persist_raw_responses`, per-model parameters, and the budget). This is
enough to explain what ran and with what settings — it is **not** a claim of
bit-for-bit reproducible LLM output; providers can and do change model
behavior over time even for an unchanged model id.

## Step 4: Aggregate scores

`benchmarks.summarize_quality(outcome.scored_cases, group_by="task")` returns
one `QualitySummary` per `(model, task)` pair, each with a mean score, median
score, optional pass rate, sample count, and a deterministic bootstrap
confidence interval. See `docs/concepts/08-quality.md` for the full aggregation
and resolution-precedence rules, including why `group_by="overall"` requires
explicit per-task weights.

## Step 5: Persist results as evidence

`BenchmarkRun` and `BenchmarkResult` are ordinary `model_compass.domain`
records; any `ObservationStore` (SQLite or in-memory) can persist and query
them with `record_benchmark_run` / `record_benchmark_result` /
`query_benchmark_runs` / `query_benchmark_results`, and export/import them
as JSONL with `export_jsonl` / `import_jsonl` (see `docs/guides/08-storage.md`).
Convert a `QualitySummary` to evidence with `.to_quality_evidence()` and
persist it with `record_quality_evidence` so selection can use it.

## Step 6: Import external evidence

`benchmarks.import_external_evidence` converts externally obtained records
(leaderboards, vendor-reported scores) into the same `QualityEvidence` shape.
It is a pure data-import function — callers supply already-extracted,
structured records; this is deliberately **not** a web scraper. Scores are
normalized only for a known `scale` (`"0-1"`, `"0-100"`, `"percentage"`); an
unrecognized scale is skipped or rejected, never assumed to already be
normalized.

## Step 7: Benchmark live, within a budget

Live, multi-model benchmarking is opt-in and bounded. `RunnerBudget` supports
`max_total_cost`, `max_cost_per_model`, and `max_cases`; the runner stops
scheduling new work for a model (or for the run) once admitting another case
would exceed the budget, based on a **conservative pre-call estimate**
(`cost_ceiling_per_case` if given, otherwise the running average of that
model's completed costs so far).

This is advisory, not a hard guarantee: provider billing that differs from
the reported response cost, or that arrives after execution, is not
detected. Never benchmark an entire catalog by default — `tests/live/test_benchmark_live.py`
only runs against one explicitly named model and requires an explicit
`MODEL_ANALYTICS_LIVE_BENCHMARK_BUDGET_USD` cost acknowledgement before it
will make a real call.

## Step 8: Score saved outputs from the CLI

`model-compass benchmark --dataset FILE.jsonl --outputs OUTPUTS.json --model MODEL_ID`
scores pre-collected string outputs against a **single-task** dataset
offline (no execution backend). It rejects multi-task datasets and cases
using the `llm_judge` evaluator — use `run_benchmark` directly for those.
Pass `--record` to persist the resulting quality evidence via the default
analytics store.

## What you learned

- How a dataset is defined, hashed, and run.
- That one failed case never discards the others.
- How scores become task-scoped quality evidence for selection.
- That live budgets are advisory, so keep them small.

## Next

[11. Custom evaluators](11-custom-evaluators.md) shows how to score outputs your own way.
