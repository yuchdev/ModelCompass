# 03. Request profiles and capability matching

**Level:** beginner · **Time:** 20 minutes · **Needs:** [01. Models](01-models.md)

In this tutorial you will build a request profile from a chat message, check which models can serve it, and compare a few candidates on a ready-made workload.

## Step 1: Build a profile from a prompt

`RequestProfile` represents the requirements of a single request without asking a model to classify it. Caller-supplied requirements take precedence over inferred values.

`build_request_profile` accepts a prompt or chat messages and conservatively infers text and image input modalities, tool use from supplied tool definitions, and structured output from an explicit response schema.

```python
from model_compass.domain import build_request_profile

request = build_request_profile(
    messages=[{"role": "user", "content": "Summarize this report."}],
    expected_output_tokens=300,
    requires_streaming=True,
)
```

It also estimates a context reservation from request size plus the expected output. That estimate is a deterministic four-characters-per-token approximation unless you supply input token usage.

## Step 2: Know what is validated

The profile validates non-negative token, context, cost, and latency values. Quality and reliability thresholds must be between zero and one. Explicit token counts remain scenario values; token estimators do not replace them by retokenizing the prompt.

## Step 3: Check eligibility

`check_eligibility` checks context, input and output modalities, tools, structured output, reasoning, and streaming. It returns explanation strings and unknown requirements.

- Missing capability metadata follows `MissingDataPolicy.REJECT` by default.
- `MissingDataPolicy.ALLOW` keeps the candidate eligible while retaining the unknowns for you to inspect.
- Quality, latency, and reliability requirements are reported as unknown until corresponding evidence exists.
- Price is not a capability.

## Step 4: Use a workload preset

`workload_scenario` provides `short-chat`, `balanced`, `input-heavy`, `long-context`, `output-heavy`, and `agent-step`. These token counts are convenience assumptions, not claims about real applications. For anything else, use `custom_workload_scenario` or build a `WorkloadScenario` with your own `RequestProfile`.

## Step 5: Compare models on a preset

Given catalog profiles in `models`, compare a few candidates for the synthetic balanced workload without making model calls:

```python
from model_compass.metrics import LiteLLMTokenEstimator
from model_compass.selection import compare_models, workload_scenario

scenario = workload_scenario("balanced")
report = compare_models(
    models[:3],  # profiles already loaded from a catalog or offline cache
    scenario.profile,
    LiteLLMTokenEstimator(),
)
for candidate in report.candidates:
    print(candidate.model.identity.canonical_id, candidate.cost.total, candidate.eligibility)
```

`ComparisonReport.to_json()` uses stable key ordering and round-trips with `ComparisonReport.model_validate_json`.

## What you learned

- How to build and validate a profile.
- How unknown capabilities are handled.
- How to try a preset workload offline.

## Next

[04. Cost estimation](04-cost-estimation.md) shows how the cost in that report is computed.
