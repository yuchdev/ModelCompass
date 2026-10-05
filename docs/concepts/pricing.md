# Pricing and cost estimates

Normalized price values are `decimal.Decimal`; JSON outputs encode them as
strings to preserve precision. OpenRouter prompt and completion prices are
interpreted as per-token rates. `estimate_cost` multiplies the known rate by
the caller-provided estimated token count; it does not infer token counts from
text.

An estimate is incomplete (`amount_usd=None`) when a nonzero token count lacks
a corresponding price or a token count is unknown. An explicit zero price is
not confused with a missing price. Conditional pricing overrides are resolved
using the request's estimated prompt-token count.

The estimate is not a guarantee of a provider's final bill. Actual costs from
execution are stored separately as empirical observations.
