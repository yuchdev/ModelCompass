# 04. Request cost estimation

**Level:** intermediate · **Time:** 15 minutes · **Needs:** [02. Pricing](02-pricing.md) and [03. Request profiles](03-request-profile.md)

In this tutorial you will estimate the cost of one request and learn how to tell a full quote from a partial one.

## Step 1: Estimate tokens

```python
from model_compass.metrics import FallbackTokenEstimator, estimate_cost

tokens = FallbackTokenEstimator().estimate(
    model="provider/model",
    prompt="A short synthetic request",
    expected_output_tokens=100,
)
```

`LiteLLMTokenEstimator` uses model-specific counts where LiteLLM's counter supports the model. If counting fails, it returns the labeled character-based approximation with `exact=False` and a fallback explanation. Explicit input token counts pass through as exact scenario values without tokenization.

## Step 2: Price the tokens

```python
cost = estimate_cost(model_profile, tokens)
print(cost.total, cost.complete, cost.assumptions)
```

`estimate_cost` combines the token usage with the model's normalized `Pricing`. It performs no model inference. Prices and arithmetic use `Decimal`.

## Step 3: See what is charged

Token prices are per-token rates. The estimator accounts for:

- input and output tokens,
- explicitly supplied cached input read and write tokens,
- explicitly supplied reasoning tokens,
- fixed per-request prices, charged when a `request` price is present,
- supplied unit usage such as image, audio, or web-search usage. Unit prices are multiplied only by usage you provide.

Cached input and reasoning token counts are subsets of their respective totals, so they replace regular token charges rather than double-charging.

## Step 4: Check completeness before trusting the total

`CostEstimate.total` is the sum of known USD components. Inspect `complete` and `assumptions` before treating it as a full quote.

- Missing prices for used components never become free. You get the known partial total with `complete=False`.
- An explicit Decimal zero price is complete and contributes zero.
- Non-USD prices are not silently converted. They make the estimate incomplete.

Pricing overrides use the effective request prompt-token count and an optional injected `now_utc`. Overrides already present on `Pricing` apply through its `effective_components` method.

## Step 5: Apply a cost ceiling

When `RequestProfile.max_cost_usd` is set, `compare_models` rejects complete estimates above the ceiling. An incomplete estimate is unknown with respect to that ceiling, and the chosen `MissingDataPolicy` decides whether it rejects the candidate.

## What you learned

- How token counts become a cost.
- That `complete` matters as much as `total`.
- How a cost ceiling treats unknown costs.

## Next

[05. Observations](05-observations.md) covers what you measure after a call, as opposed to what you estimate before it.
