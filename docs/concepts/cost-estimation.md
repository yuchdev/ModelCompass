# Request cost estimation

`estimate_cost` combines an estimated request's token usage with a model's normalized
`Pricing`. It performs no model inference. Prices and arithmetic use `Decimal`.
`CostEstimate.total` is the sum of known USD components; inspect `complete` and
`assumptions` before treating a total as a full quote.

Token prices are applied as per-token rates. The estimator accounts for input and
output tokens, explicitly supplied cached input read/write tokens, explicitly supplied
reasoning tokens, fixed per-request prices, and optional supplied unit usage such as
image, audio, or web-search usage. Cached input and reasoning token counts are treated
as subsets of their respective total token counts, so they replace rather than
double-charge those regular token components. Fixed request fees are charged when a
`request` price is present. Unit-based prices are multiplied only by usage explicitly
provided by the caller.

Pricing overrides use the effective request prompt-token count and an optional injected
`now_utc` timestamp. Overrides already present on `Pricing` apply through its
`effective_components` method. Missing prices for used components never become free:
the known partial total is returned with `complete=False`. An explicit Decimal zero
price is complete and contributes zero. Non-USD prices are not silently converted;
they make the estimate incomplete.

```python
from model_compass.metrics import FallbackTokenEstimator, estimate_cost

tokens = FallbackTokenEstimator().estimate(
    model="provider/model",
    prompt="A short synthetic request",
    expected_output_tokens=100,
)
cost = estimate_cost(model_profile, tokens)
print(cost.total, cost.complete, cost.assumptions)
```

LiteLLM token counts are model-specific where its counter supports the model. If
counting fails, `LiteLLMTokenEstimator` returns the labeled character-based
approximation with `exact=False` and a fallback explanation. Explicit input token
counts are passed through as exact scenario values without tokenization.

When `RequestProfile.max_cost_usd` is set, `compare_models` rejects complete estimates
above the ceiling. An incomplete estimate is unknown with respect to that ceiling;
the selected `MissingDataPolicy` decides whether unknown costs reject the candidate.
