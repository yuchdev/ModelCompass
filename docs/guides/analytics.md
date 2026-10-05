# Analytics and selection

## Describe a workload

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

Unknown required capability support is rejected by default. A quality or
latency threshold also rejects candidates without matching evidence by
default. Customize these rules explicitly with `SelectionDataPolicy`.

Candidates are also rejected when a known `max_output_tokens` limit is below
`expected_output_tokens`. Cost estimates add the per-request price component
(when present) once per estimate, alongside prompt and completion token costs.

The `select` CLI exposes these constraints, including `--input-modality` and
`--output-modality` (repeatable) and `--minimum-context`.

## Choose a policy

Pass normalized profiles to `analytics.select(profiles, request, policy=...)`.
Policies are `cheapest`, `best`, `fastest`, `most-reliable`, and
`cost-efficient`. Cost efficiency is quality divided by estimated cost; a
zero-cost candidate is ordered ahead of nonzero-cost candidates. It is a
transparent heuristic, not a universally optimal score.

`SelectionResult.assessments` explains eliminations and missing evidence.
`pareto_frontier` exposes tradeoffs across quality/reliability (maximize) and
cost/latency (minimize) without collapsing them to one score.

For the detailed constraint reason codes, evidence types, conservative
reliability estimator, and policy tie-break rules, see the
[selection policies guide](selection-policies.md), [selection concept](../concepts/selection.md),
and [Pareto concept](../concepts/pareto.md).

## Observations

An `Observation` records a task label, model, timestamp, success, latency, token
counts, optional actual cost, and optional quality score. It intentionally has
no prompt/message field. `analytics.record_observation(...)` stores it in the
local SQLite database; `analytics.list_observations(task=...)` retrieves it.
Summaries report sample size and only aggregate observations for the exact
requested task.

## Benchmarks

`evaluate_benchmark` is network-free: provide a `BenchmarkDataset` and a
mapping of case IDs to already-obtained outputs. Exact, regular-expression,
and JSON evaluators produce per-case results and a Decimal quality score. The
CLI accepts JSON dataset and output files with `model-compass benchmark`.
`--record` stores the score, evaluator, dataset, task, and sample count as
quality evidence. Datasets with duplicate case IDs and invalid regular-expression
patterns are rejected with `BenchmarkError`. Benchmark quality is stored separately from execution
reliability/latency, and selection uses matching task evidence only.

Storage errors, including failure to create the database directory, are raised
as `StorageError`.
