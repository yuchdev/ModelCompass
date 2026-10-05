# Request profiles and capability matching

`RequestProfile` represents requirements for a single request without asking a model
to classify it. Caller-supplied requirements take precedence over inferred values.
`build_request_profile` accepts a prompt or chat messages and conservatively infers
text/image input modalities, tool use from supplied tool definitions, and structured
output from an explicit response schema. It estimates a context reservation from
request size plus the expected output; that context estimate is a deterministic
four-characters-per-token approximation unless the caller supplies input token usage.

```python
from model_compass.domain import build_request_profile

request = build_request_profile(
    messages=[{"role": "user", "content": "Summarize this report."}],
    expected_output_tokens=300,
    requires_streaming=True,
)
```

The profile validates non-negative token, context, cost, and latency values. Quality
and reliability thresholds must be between zero and one. Explicit token counts remain
scenario values; token estimators do not replace them by retokenizing the prompt.

`check_eligibility` checks context, input/output modalities, tools, structured output,
reasoning, and streaming. It returns explanation strings and unknown requirements.
Missing capability metadata follows `MissingDataPolicy.REJECT` by default;
`MissingDataPolicy.ALLOW` keeps the candidate eligible while retaining the unknowns
for callers to inspect. Quality, latency, and reliability requirements are reported
as unknown until corresponding evidence is implemented. Price is not a capability.

## Synthetic workload presets

`workload_scenario` provides `short-chat`, `balanced`, `input-heavy`, `long-context`,
`output-heavy`, and `agent-step`. These token counts are convenience assumptions, not
claims about actual applications. Use `custom_workload_scenario` or construct a
`WorkloadScenario` with a custom `RequestProfile` for other workloads.

## Compare models

Given catalog profiles in `models`, compare a few candidates for the synthetic
balanced workload without making model calls:

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

The returned `ComparisonReport.to_json()` uses stable JSON key ordering and can be
round-tripped with `ComparisonReport.model_validate_json`.
