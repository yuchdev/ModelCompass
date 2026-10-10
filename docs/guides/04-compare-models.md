# 04. Compare models

**Level:** beginner · **Time:** 10 minutes · **Needs:** a list of `ModelProfile`s (see [02. Catalogs](02-catalogs.md))

Sometimes you do not want a single winner; you want to see every candidate next to the others. In this tutorial you will compare models for one request and read the report.

## Step 1: Describe the request

```python
from decimal import Decimal

from model_compass import RequestProfile

request = RequestProfile(task="code_review", explicit_input_tokens=12_000, expected_output_tokens=1_000)
```

## Step 2: Run the comparison

`compare_models()` needs a token estimator. `FallbackTokenEstimator` is character-based and needs no extra dependency.

```python
from model_compass.metrics import FallbackTokenEstimator
from model_compass.selection import compare_models

report = compare_models(
    models,
    request,
    FallbackTokenEstimator(),
    max_cost_usd=Decimal("0.05"),
)
```

## Step 3: Read the report

```python
for candidate in report.candidates:
    print(candidate.model.identity.canonical_id, candidate.eligibility.eligible, candidate.cost.total)
```

Each candidate keeps its eligibility, cost estimate, evidence, and rank for each policy. An ineligible model stays in the report with the reason it failed, so you can see why it was dropped.

## What you learned

- That `compare_models` explains the field instead of picking one winner.
- That every candidate carries its own eligibility result and cost estimate.

## Next

[05. Select a model](05-select-model.md) turns the same inputs into a single decision.
