# Compare models

`compare_models()` gives you a side-by-side view of eligible candidates without selecting one for you.

```python
from decimal import Decimal

from model_compass import RequestProfile
from model_compass.metrics import FallbackTokenEstimator
from model_compass.selection import compare_models

request = RequestProfile(task='code_review', explicit_input_tokens=12_000, expected_output_tokens=1_000)
report = compare_models(
    models,
    request,
    FallbackTokenEstimator(),
    max_cost_usd=Decimal('0.05'),
)
for candidate in report.candidates:
    print(candidate.model.identity.canonical_id, candidate.eligibility.eligible, candidate.cost.total)
```

Use this when you want the reasoning, not just the final winner. Each candidate keeps its eligibility, estimate, evidence, and rank-by-policy information.

If you already know the hard requirements you want to enforce, see [Select model](select-model.md).
