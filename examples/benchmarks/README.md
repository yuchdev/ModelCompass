# Sample benchmark dataset

`sample.jsonl` is a tiny, hand-authored dataset exercising every
built-in deterministic evaluator (`exact`, `normalized_exact`, `regex`,
`contains_terms`, `json_validity`, `json_schema`, `numeric_tolerance`) across
three tasks (`qa`, `extraction`, `summarization`). It was generated with
`model_compass.benchmarks.dump_dataset_jsonl` and can be round-tripped with
`load_dataset_jsonl`.

See `docs/guides/10-benchmarks.md` for the full dataset format and how to run it
against a real or fake execution backend.

```python
from pathlib import Path

from model_compass.benchmarks import load_dataset_jsonl

text = Path("examples/benchmarks/sample.jsonl").read_text(encoding="utf-8")
dataset = load_dataset_jsonl(text)
print(dataset.identity)
```

This dataset spans more than one task, so it is meant for `run_benchmark` (or
`uv run model-compass benchmark`-style offline scoring restricted to a single
task's cases) rather than the single-task-only `evaluate_offline` helper.
