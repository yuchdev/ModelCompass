# 09. Execution

**Level:** advanced · **Time:** 30 minutes · **Needs:** [05. Observations](05-observations.md) and [06. Selection](06-selection.md)

In this tutorial you will follow one request from selection through a real call to a stored observation, and learn how cost is reconciled afterwards.

Execution turns a selection into a real model call and measures what happened. It is
deliberately separate from selection: `selection`, `domain`, and `storage` never import
LiteLLM or the `execution` package.

## Step 1: Learn the protocol

```python
class ExecutionBackend(Protocol):
    async def execute(self, request: ExecutionRequest) -> ExecutionResult: ...
```

Anything implementing `execute` can replace LiteLLM. `LiteLLMBackend` is the shipped
implementation (see the [LiteLLM guide](../guides/09-litellm.md)); tests use
`tests.fixtures.fake_execution_backend.FakeExecutionBackend`.

## Step 2: Build a request

`ExecutionRequest` is a frozen, serializable DTO: `model_id`, `task`, `messages`, optional
`tools`, optional `response_format` (structured output), `parameters`, `stream`,
`provider_routing`, and opaque caller `metadata`. `ExecutionRequest.from_prompt` builds a
single-user-message request.

Credentials are not representable: keys such as `api_key`, `authorization`, `password`, or
`*_api_key` (at any depth) are rejected at construction. Give the API key to the backend.
Keys that would make the provider layer switch models behind your back (`fallbacks`,
`models`, `route`, ...) are rejected too — v1 has no implicit multi-model fallback.
Caller `metadata` is passed through but never persisted.

## Step 3: Read the result

`ExecutionResult` carries the output text, any `tool_calls`, `latency_ms` (monotonic
clock), `time_to_first_token_ms` (streaming only), `finish_reason` and a derived `status`
(`completed`, `truncated`, `content_filtered`, `unknown`), and a `UsageRecord`:

| Field | Meaning |
|---|---|
| `input_tokens`, `output_tokens`, `total_tokens` | Provider-reported counts |
| `cached_read_tokens`, `cached_write_tokens` | Prompt-cache usage |
| `reasoning_tokens` | Hidden reasoning usage |
| `provider_specific` | Remaining usage fields, preserved verbatim |

Any field is `None` when the provider did not report it — never `0`. The record only
rejects negative values and a `total_tokens` smaller than its input or output, because
providers disagree on whether cache and reasoning counts are included in or additional to
input/output.

### Tell actual cost from computed cost

Costs are `Decimal` and kept apart:

- `actual_cost_usd` — only when LiteLLM/the provider exposed a cost for this response.
- `computed_cost_usd` — a post-hoc estimate priced from reported usage, recorded only
  when no actual cost is available.
- `cost_source` — `"provider_reported"`, `"computed"`, or `None`.

## Step 4: Reconcile estimated and actual cost

`reconcile_costs(estimated_before, actual_after, actual_source=...)` returns a
`CostReconciliation(estimated_before, actual_after, absolute_error, relative_error,
actual_source)`.

- `absolute_error = |actual - estimated|`; `relative_error = absolute_error / actual`.
- If either side is unavailable the reconciliation is **incomplete**
  (`is_complete is False`) and both errors are `None` — not zero.
- When the actual cost is zero, the relative error is `0` for a zero estimate and `None`
  otherwise (undefined).

```python
from decimal import Decimal
from model_compass.execution import reconcile_costs

r = reconcile_costs(Decimal("0.0020"), Decimal("0.0018"), actual_source="provider_reported")
assert r.absolute_error == Decimal("0.0002")
assert r.is_complete

assert reconcile_costs(Decimal("0.0020"), None).relative_error is None
```

## Step 5: See what is stored

A successful execution is stored as a domain `Observation` (no prompt or response text):
tokens (including cache and reasoning), `actual_cost`, `estimated_cost` (the pre-request
estimate when there was one, otherwise the computed cost), `cost_source`, latency, TTFT,
`finish_reason`, and `metadata["cost_reconciliation"]`.
A failed execution is stored with `success=False`, a `failure_category`, and the latency
seen so far; the provider's error text is never stored.

Failure categories: `timeout`, `authentication`, `rate_limit`, `context_length`,
`bad_request`, `connection`, `provider_error`, `malformed_response`, `partial_output`.
All are subclasses of `ExecutionError` (a `ModelCompassError`) with a `category`.

Persistence goes through an `ObservationSink` (any store's `record_observation`).
`NullObservationSink` discards observations for execution without persistence.

## Step 6: Select and execute in one call

```python
result = await analytics.select_and_execute(
    profiles=profiles,
    request_profile=request_profile,
    execution_request=execution_request,
    policy="cheapest",
)
result.selection  # SelectionResult
result.execution  # ExecutionResult
result.observation_id  # id of the stored observation
result.reconciliation  # CostReconciliation vs. the selector's expected cost
```

The selected model replaces `execution_request.model_id`. If no model is eligible,
`NoEligibleModelError` is raised before anything executes. On an execution failure the
failure is recorded and re-raised with `observation_id` set on the exception.
The request profile's task (or `general` when omitted) must match
`execution_request.task`; mismatches are rejected before selection.

## Step 7: Understand retries and fallbacks

There is no multi-model fallback. LiteLLM may retry the **same** model for transport and
provider failures when you configure `max_retries` on the backend (bounded at 5, default
0). Every retry can be billed by the provider, and LiteLLM does not report how many
occurred; the configured value is in `result.metadata["max_retries"]`. A future fallback
policy would be an explicit caller-supplied choice.

## What you learned

- Any object with an async `execute` can be a backend.
- Unreported usage is `None`, never `0`, and estimated and actual costs stay separate.
- A failed call is recorded without provider error text.
- There is no hidden multi-model fallback.
