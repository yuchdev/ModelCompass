# 06. Analytics and selection

**Level:** intermediate · **Time:** 20 minutes · **Needs:** [05. Select a model](05-select-model.md)

In this tutorial you will describe a demanding workload, choose a policy, and then start feeding real outcomes back into selection with observations and benchmarks.

## Step 1: Describe a workload

```python
from decimal import Decimal

from model_compass import RequestProfile

request = RequestProfile(
    task="code_review",
    input_modalities={"text"},
    output_modalities={"text"},
    explicit_input_tokens=40_000,
    expected_output_tokens=2_000,
    requires_tools=True,
    minimum_context=64_000,
    max_cost_usd=Decimal("0.05"),
    min_quality=Decimal("0.90"),
)
```

Unknown required capability support is rejected by default. A quality or latency threshold also rejects candidates without matching evidence by default. Customize these rules explicitly with `SelectionDataPolicy`.

Candidates are also rejected when a known `max_output_tokens` limit is below `expected_output_tokens`. Cost estimates add the per-request price component (when present) once per estimate, alongside prompt and completion token costs.

The `select` CLI exposes the same constraints, including `--input-modality` and `--output-modality` (repeatable) and `--minimum-context`.

## Step 2: Choose a policy

Pass normalized profiles to `analytics.select(profiles, request, policy=...)`. Policies are `cheapest`, `best`, `fastest`, `most-reliable`, and `cost-efficient`. Cost efficiency is quality divided by estimated cost; a zero-cost candidate is ordered ahead of nonzero-cost candidates. It is a transparent heuristic, not a universally optimal score.

## Step 3: Ask why

`SelectionResult.assessments` explains eliminations and missing evidence. `pareto_frontier` exposes tradeoffs across quality and reliability (maximize) and cost and latency (minimize) without collapsing them to one score.

## Step 4: Record observations

An `Observation` records a task label, model, timestamp, success, latency, token counts, optional actual cost, and optional quality score. It intentionally has no prompt or message field.

- `analytics.record_observation(...)` stores one in the local SQLite database.
- `analytics.list_observations(task=...)` retrieves them.
- Summaries report sample size and only aggregate observations for the exact requested task.

Storage errors, including failure to create the database directory, are raised as `StorageError`.

## Step 5: Score outputs with a benchmark

`evaluate_benchmark` is network-free: provide a `BenchmarkDataset` and a mapping of case IDs to already-obtained outputs. Exact, regular-expression, and JSON evaluators produce per-case results and a Decimal quality score.

From the CLI, use `model-compass benchmark` with JSON dataset and output files. `--record` stores the score, evaluator, dataset, task, and sample count as quality evidence. Datasets with duplicate case IDs and invalid regular-expression patterns are rejected with `BenchmarkError`.

Benchmark quality is stored separately from execution reliability and latency, and selection uses matching task evidence only.

## What you learned

- How to express modality, tool, context, cost, and quality requirements.
- Where to look when a model is eliminated.
- How observations and benchmarks become evidence for later selections.

## Next

[07. Selection policies](07-selection-policies.md) goes into the exact ordering rules. The [selection concept](../concepts/06-selection.md) and [Pareto concept](../concepts/07-pareto.md) pages give the background.
