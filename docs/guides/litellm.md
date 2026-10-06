# Executing with LiteLLM

`LiteLLMBackend` runs an `ExecutionRequest` through `litellm.acompletion` and normalizes
the response. See [Execution](../concepts/execution.md) for the data model.

## Basic use

```python
from model_compass.execution import ExecutionRequest, LiteLLMBackend

backend = LiteLLMBackend()  # reads provider keys from the environment, as LiteLLM does
request = ExecutionRequest.from_prompt(
    "openai/gpt-4o-mini", "qa", "What is 2+2?", parameters={"max_tokens": 16}
)
result = await backend.execute(request)
print(result.output_text, result.usage, result.actual_cost_usd)
```

`LiteLLMBackend.execute` is async. Use `asyncio.run(...)` at an application boundary; the
sync `analytics.refresh`-style facades are not provided for execution.

Options:

| Option | Purpose |
|---|---|
| `api_key` | Passed to LiteLLM; never stored in requests, results, observations, errors, or `repr` |
| `max_retries` | LiteLLM `num_retries` for the *same* model, 0–5 (default 0) |
| `model_resolver` | Maps a canonical `provider:model` id to LiteLLM's model string |
| `cost_call` | `(model, input_tokens, output_tokens) -> Decimal \| None`; default uses LiteLLM's price table |
| `on_text_delta` | Callback receiving each streamed text delta |

Retries can multiply cost: each attempt may be billed. The count actually used is not
reported by LiteLLM, so only the configured maximum is recorded.

## Tools, structured output, routing

`tools` and `response_format` on the request are forwarded unchanged. Returned tool calls
are preserved in `result.tool_calls`; JSON output stays in `output_text`.
`provider_routing` is sent as `extra_body={"provider": ...}` (OpenRouter provider routing)
and is only applied when you set it.

## Streaming

Set `stream=True` on the request. The backend consumes a real provider stream
(`stream_options={"include_usage": True}`), measures time to first token with a monotonic
clock, merges fragmented tool calls, and returns one final `ExecutionResult` — observation
recording happens only after the stream finishes or fails. Use `on_text_delta` to see text
as it arrives. If the stream fails after output was received, `PartialOutputError` is raised
with `partial_output`, and the stored observation is marked `failure_category="partial_output"`
with `metadata["partial_output"] = True`.

Usage and cost are only available if the provider sends them in the stream; otherwise they
are `None`.

## Errors and secrets

LiteLLM and generic provider exceptions are mapped to `ExecutionError` subclasses. Messages
contain only the exception *type* — provider text is dropped because it can echo
credentials. Exceptions keep the original as `__cause__` for debugging; do not log
tracebacks where that matters.

## Select, execute, reconcile

```python
from decimal import Decimal
from model_compass.application import AnalyticsFacade
from model_compass.storage import InMemoryObservationStore

facade = AnalyticsFacade(observation_store=InMemoryObservationStore())
outcome = await facade.select_and_execute(
    profiles=profiles,
    request_profile=request_profile,
    execution_request=ExecutionRequest.from_prompt("unused", "qa", "What is 2+2?"),
    policy="cheapest",
    backend=LiteLLMBackend(model_resolver=lambda canonical: canonical.replace(":", "/")),
)

r = outcome.reconciliation
if r.is_complete:
    print(f"estimated {r.estimated_before}, actual {r.actual_after}, error {r.relative_error:.1%}")
else:
    print("no actual cost reported; reconciliation incomplete")
```

Pass `observation_sink=NullObservationSink()` to skip persistence. Selection reads evidence
from the facade's own store, so use an in-memory store (as above) to avoid touching disk.

## Testing

Mandatory tests mock LiteLLM at the `completion_call` boundary and need no credentials:

```python
async def fake_completion(**kwargs):
    return {"choices": [{"message": {"content": "ok"}, "finish_reason": "stop"}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 1}}

backend = LiteLLMBackend(completion_call=fake_completion)
```

Live tests are opt-in:

```text
MODEL_ANALYTICS_LIVE_LLM=1
MODEL_ANALYTICS_LIVE_MODEL=<explicit LiteLLM model id>
MODEL_ANALYTICS_LIVE_MAX_COST_USD=0.01   # optional ceiling checked before the request
```

The live test sends a tiny prompt and records into a temporary database.
