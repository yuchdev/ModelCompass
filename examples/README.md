# Model Compass examples

Seven small, runnable scripts plus one sample dataset. Each one isolates a single question you would ask when choosing an LLM, and answers it with the smallest piece of the public API that can do the job.

Everything here runs **offline with no API keys**, except `execute_with_litellm.py`, which is a dry run unless you opt in.

```bash
uv sync --all-groups
uv run python examples/list_models.py
```

Run the scripts from the repository root. The scripts import `_demo_common` from this directory, which Python finds because the script's own directory is on `sys.path`.

## How to read this directory

The examples are ordered from the simplest question to the most involved. Each section follows the same shape: the problem, the approach, how the solution helps, why the API looks the way it does, and what to take away.

| # | Script | Question it answers | Learn more |
|---|---|---|---|
| 1 | [`list_models.py`](#1-list_modelspy--what-models-do-i-have) | What models do I have, and what can they do? | [Models](../docs/concepts/01-models.md), [Catalogs](../docs/guides/02-catalogs.md) |
| 2 | [`estimate_cost.py`](#2-estimate_costpy--what-will-this-request-cost) | What will this request cost? | [Cost estimation](../docs/concepts/04-cost-estimation.md), [Pricing](../docs/concepts/02-pricing.md) |
| 3 | [`compare_models.py`](#3-compare_modelspy--how-do-the-candidates-stack-up) | How do the candidates stack up? | [Compare models](../docs/guides/04-compare-models.md) |
| 4 | [`constrained_selection.py`](#4-constrained_selectionpy--which-single-model-should-i-use) | Which single model should I use? | [Select a model](../docs/guides/05-select-model.md), [Selection](../docs/concepts/06-selection.md) |
| 5 | [`pareto_frontier.py`](#5-pareto_frontierpy--what-tradeoffs-am-i-making) | What tradeoffs am I making? | [Pareto analysis](../docs/concepts/07-pareto.md) |
| 6 | [`benchmark_fake_backend.py`](#6-benchmark_fake_backendpy--how-good-is-a-model-at-my-task) | How good is a model at my task? | [Benchmarks](../docs/guides/10-benchmarks.md), [Quality evidence](../docs/concepts/08-quality.md) |
| 7 | [`execute_with_litellm.py`](#7-execute_with_litellmpy--how-do-i-actually-call-it) | How do I actually call the model? | [Executing with LiteLLM](../docs/guides/09-litellm.md), [Execution](../docs/concepts/09-execution.md) |

## Shared fixtures: `_demo_common.py`

Examples 1–5 share two hand-built models and one request, so their outputs can be compared.

- `demo_profiles()` returns `demo:small` (8k context, `$0.000001` per prompt token, `$0.000002` per completion token) and `demo:large` (16k context, three times the price).
- `demo_request()` is a summarization request with 2,000 input tokens, 500 expected output tokens, a `$0.02` ceiling, and `min_quality=0.85`.

**Why synthetic profiles?** Real catalog data changes daily. A demo built on it would print different numbers every run and need a network. Synthetic profiles make the output deterministic and keep the focus on the API. To get real profiles, see [02. Catalogs](../docs/guides/02-catalogs.md) and [03. Offline use](../docs/guides/03-offline-use.md).

**Why `Decimal` prices written as strings?** `Decimal("0.000001")` is exact; `0.000001` as a float is not. Money in this library is always `Decimal` (see [02. Pricing](../docs/concepts/02-pricing.md)).

---

## 1. `list_models.py` — what models do I have?

**The problem.** Before you can compare anything, you need one consistent view of the models. OpenRouter, LiteLLM, and your own deployments all describe a model differently: different field names, different units, and different gaps. Code that reads each source directly ends up full of special cases.

**The approach.** Normalize first. Every source is converted into a `ModelProfile`, which has an identity, capabilities, pricing, and provenance. The canonical ID is always `provider:model_id`. This example reads the normalized fields, never raw source fields.

**How it helps.** Everything downstream (cost, eligibility, selection) works on `ModelProfile` and has no idea where the data came from. Swapping the data source changes nothing else. Missing source fields stay `UNKNOWN` rather than becoming a guess, so a gap in the data is visible instead of silently wrong.

**Why this API.**

- The output is plain JSON built from `profile.identity` and `profile.capabilities`. That is deliberate: it is the same shape the CLI emits with `model-compass models --format json`, so you can move between script and CLI.
- `sort_keys=True` makes the output stable and easy to diff in tests.
- It lists modalities rather than prices because modalities are the first hard filter a request hits.

**Takeaways.**

- A `ModelProfile` is the unit everything else operates on.
- `provider:model_id` is the stable key used in every report and evidence lookup.
- For the live catalog, use `uv run model-compass models list`.

**Read next:** [Models, requests, and evidence](../docs/concepts/01-models.md), [Catalogs](../docs/guides/02-catalogs.md).

---

## 2. `estimate_cost.py` — what will this request cost?

**The problem.** Per-token prices are tiny numbers, and real bills have more than two components: prompt, completion, cached reads, reasoning tokens, fixed per-request fees. Doing this by hand is error-prone. The worse failure is silent: if one price is missing, a naive calculation treats it as free and reports a total that is too low.

**The approach.** Split the job in two. A `TokenEstimator` turns the request into token counts, and `estimate_cost` turns counts plus a model's `Pricing` into a `CostEstimate`. The estimate carries its own honesty flags: `complete` and a list of `assumptions`.

**How it helps.** The script prints:

```json
{
  "assumptions": [
    "Input token count supplied explicitly; it was not retokenized.",
    "Output token count is the expected scenario value."
  ],
  "complete": true,
  "pricing_source": "catalog",
  "total": "0.003000"
}
```

You get a number and the conditions it holds under. Check by hand: 2,000 × `0.000001` + 500 × `0.000002` = `0.002` + `0.001` = `0.003`. Missing prices never become zero. They produce `complete=False` with the known partial total.

**Why this API.**

- `FallbackTokenEstimator` is character-based and needs no extra dependency, which keeps the example runnable anywhere. In real use, `LiteLLMTokenEstimator` gives model-specific counts and falls back to the same approximation, labeled `exact=False`, when it cannot count.
- The script passes `explicit_input_tokens` because when you already know the count, the estimator passes it through untouched instead of re-tokenizing it.
- Estimation is separate from pricing so that token counting (which varies per model) can change independently of price arithmetic.

**Takeaways.**

- Always read `complete` before trusting `total`.
- An explicit zero price is complete; a missing price is not.
- An estimate is a forecast, not a bill. Actual cost is recorded separately after a call (see example 7).

**Read next:** [Request cost estimation](../docs/concepts/04-cost-estimation.md), [Pricing and cost estimates](../docs/concepts/02-pricing.md).

---

## 3. `compare_models.py` — how do the candidates stack up?

**The problem.** A single "best model" answer hides the reasoning. When it is wrong, you cannot tell whether the model was too expensive, lacked a capability, or simply had no data. You want the whole field laid out, with reasons.

**The approach.** `compare_models` evaluates every candidate against the request and returns a `ComparisonReport`: eligibility, a cost estimate, evidence, and ranks for each candidate. It does not pick a winner for you.

**How it helps.** Running the script prints:

```json
{
  "candidates": [
    {"cost": "0.009000", "eligible": false, "model_id": "demo:large"},
    {"cost": "0.003000", "eligible": false, "model_id": "demo:small"}
  ],
  "selected_policy": "best"
}
```

**Both models are ineligible, and that is correct.** `demo_request()` sets `min_quality=0.85`, but this example supplies no quality evidence. The reasons on each candidate say so: *"quality evidence is missing"* and *"no quality evidence for task 'summarization'"*. Under the default `MissingDataPolicy.REJECT`, missing data never satisfies a hard positive requirement. Example 4 supplies the evidence and the same request succeeds.

This is the point of the example: the report tells you *why*, so you can fix the input rather than guess.

**Why this API.**

- It takes the estimator as an explicit argument rather than constructing one internally, so you choose exact versus approximate token counting.
- Costs are shown per candidate, using that model's own token estimate. Tokenizers differ, so the same prompt can cost differently.
- `str(candidate.cost.total)` is used in the output because `Decimal` serializes exactly as a string, and as a JSON float it would not.

**Takeaways.**

- Use `compare_models` to understand, and `select` to decide.
- Ineligible candidates stay in the report with reasons. They are not silently dropped.
- A hard requirement with no evidence fails by design. Supply evidence, or opt in to `MissingDataPolicy.ALLOW` and accept that unknowns are kept but not invented.

**Read next:** [Compare models](../docs/guides/04-compare-models.md), [Request profiles and capability matching](../docs/concepts/03-request-profile.md).

---

## 4. `constrained_selection.py` — which single model should I use?

**The problem.** Now you want one answer: the cheapest model that is still good enough. "Good enough" needs evidence, and evidence has to be for *your task*. A model that scores well on coding says nothing about summarization.

**The approach.** Two stages. Hard constraints (quality, cost, context, capabilities, allow and block lists) remove candidates first. Then the policy, here `CHEAPEST`, ranks the survivors. Quality comes from a `QualityProvider`; this example uses `InMemoryQualityProvider` with `MetricEvidence` values that record the score, its source, the exact task, and the sample count.

**How it helps.** The script prints:

```json
{
  "rejections": {},
  "selected": "demo:small",
  "selected_policy": "cheapest"
}
```

Both models clear the 0.85 bar (0.91 and 0.97), so the cheaper one wins. Had `demo:small` scored 0.80, it would appear in `rejections` and `demo:large` would be selected, with the reason code preserved.

**Why this API.**

- `analytics.select(...)` is the high-level entry point; `select_model` (used in example 5) is the lower-level function it wraps.
- Evidence is a typed object, not a bare number, so the result can state where a quality score came from and how many samples back it.
- Filters run before ranking, so a cheap model that fails quality never competes on price.
- `rejection_counts` is part of the result so that an empty answer is explainable. Pass `raise_on_empty=True` if you would rather get a `NoEligibleModelError`.

**Takeaways.**

- Constrain first, then optimize.
- Quality evidence is task-scoped; selection never substitutes a different task's score.
- Policies are named (`cheapest`, `best`, `fastest`, `most-reliable`, `cost-efficient`), and each has documented tie-breakers.

**Read next:** [Select a model](../docs/guides/05-select-model.md), [Selection policies](../docs/guides/07-selection-policies.md), [Model selection](../docs/concepts/06-selection.md).

---

## 5. `pareto_frontier.py` — what tradeoffs am I making?

**The problem.** Example 4 collapses everything to one rule: cheapest. But cost and quality pull in opposite directions, and any single score that blends them embeds a weighting you never chose. Sometimes the right answer is *"here are the options worth considering"*.

**The approach.** Keep the tradeoff. A Pareto frontier is the set of candidates that no other candidate beats on every objective at once. The script runs `select_model` with the `BEST` policy, then passes the assessments to `pareto_frontier` with two objectives: quality (maximize) and cost (minimize).

**How it helps.** The output:

```json
{
  "frontier": ["demo:large", "demo:small"],
  "selected": "demo:large"
}
```

Neither model dominates. `demo:large` is better but costs three times as much, and `demo:small` is cheaper but weaker. Both are legitimate choices, so both stay on the frontier. The `BEST` policy picks `demo:large`, but the frontier shows you that `demo:small` is the cost-conscious alternative. If a third model were both pricier and weaker than `demo:small`, it would be dropped.

**Why this API.**

- `ParetoObjective.QUALITY` and `ParetoObjective.COST` come with built-in directions, so you cannot accidentally maximize cost. For custom metrics you pass a mapping to `ObjectiveDirection.MINIMIZE` or `MAXIMIZE`.
- It accepts the same assessments `select_model` already produced, so there is no recomputation.
- Missing objective values are excluded by default; you can opt in to raising instead.

**Takeaways.**

- A frontier does not choose for you. It removes the choices that are clearly worse.
- Showing a frontier is more honest than inventing a weighted score.
- The frontier and the policy winner answer different questions, and the winner is always on the frontier.

**Read next:** [Pareto analysis](../docs/concepts/07-pareto.md), [Analytics and selection](../docs/guides/06-analytics.md).

---

## 6. `benchmark_fake_backend.py` — how good is a model at my task?

**The problem.** Examples 4 and 5 assumed quality scores existed. Where do they come from? Public leaderboards measure other tasks, and a live benchmark costs money and varies from run to run. You need a repeatable process you can test without spending anything.

**The approach.** Put a seam between the benchmark runner and the model call. Execution is a protocol, `ExecutionBackend`, with one method: `async def execute(request) -> ExecutionResult`. The script implements a `FakeBackend` that always answers `"Paris"` and feeds it to the real `run_benchmark`.

**How it helps.** The dataset has one case: *What is the capital of France?*, scored by the `exact` evaluator. The output:

```json
{
  "dataset": "demo",
  "results": 1,
  "score": "1"
}
```

That is the entire real pipeline (dataset, runner, evaluator, budget, result) with the network swapped out. The `RunnerBudget(max_total_cost=Decimal("0.01"))` also shows the budget guard: the fake reports `0.001` per call, so the runner would stop scheduling work after about ten.

**Why this API.**

- A backend is a protocol rather than a base class, so any object with an async `execute` works, including `LiteLLMBackend` in production. The same `run_benchmark` call runs unchanged against either.
- Evaluators are deterministic by default (`exact`, `regex`, `json_schema`, ...), so a score does not change between runs. An LLM judge exists but is strictly opt-in.
- A frozen `BenchmarkDataset` cannot be mutated mid-run, and its identity hash is computed from content, not stored.
- Results carry `Decimal` scores, and one failed case never discards the others.

**Takeaways.**

- Tests and demos should not need a network. Design the seam first.
- A benchmark score is evidence tied to a task, dataset, and version, and it feeds the `QualityProvider` from example 4.
- Budgets are advisory estimates, not guarantees.

**The sample dataset.** [`benchmarks/sample.jsonl`](benchmarks/sample.jsonl) exercises every built-in evaluator across three tasks (`qa`, `extraction`, `summarization`). See [`benchmarks/README.md`](benchmarks/README.md) for how to load it. `sample-dataset.jsonl` is a byte-identical copy kept for compatibility with older docs and tests.

**Read next:** [Benchmarks](../docs/guides/10-benchmarks.md), [Custom evaluators](../docs/guides/11-custom-evaluators.md), [Quality evidence](../docs/concepts/08-quality.md).

---

## 7. `execute_with_litellm.py` — how do I actually call it?

**The problem.** Selection is only useful if you can act on it. A real call needs credentials, can fail in a dozen ways, can leak secrets in error text, and can cost real money. A demo that makes a live call by default would surprise anyone who ran it.

**The approach.** Dry-run by default, opt-in to live. The script builds an `ExecutionRequest` and stops unless you set `MODEL_COMPASS_EXAMPLE_RUN_LITELLM=1`. The model comes from `MODEL_COMPASS_EXAMPLE_MODEL_ID` (default `openai/gpt-4o-mini`). With the flag set, `LiteLLMBackend().execute(request)` makes the call.

```bash
# Dry run: prints the request it would send, makes no call
uv run python examples/execute_with_litellm.py

# Live: needs provider credentials in the environment, and costs money
MODEL_COMPASS_EXAMPLE_RUN_LITELLM=1 uv run python examples/execute_with_litellm.py
```

**How it helps.** The backend reads provider keys from the environment as LiteLLM does and never stores them in requests, results, observations, or errors. `ExecutionRequest` rejects credential-shaped keys at construction. The request is capped at `max_tokens=16`, so even a live run is tiny.

**Why this API.**

- `ExecutionRequest.from_prompt(model_id, task, prompt, ...)` builds the common single-message request in one line. The `task` argument is required because observations are task-scoped.
- `execute` is `async` because real calls are I/O-bound and streaming needs it. The script calls `asyncio.run(...)` once at the application boundary.
- There is no implicit fallback to another model, so a call is never silently re-routed. Retries, if configured, are for the same model and are documented as billable.
- `selection`, `domain`, and `storage` never import `execution`, so selection stays testable without LiteLLM.

**Takeaways.**

- Make the safe path the default and the expensive path an explicit choice.
- Credentials belong to the backend, not the request.
- After a live call, reconcile the estimate from example 2 against the actual cost. `AnalyticsFacade.select_and_execute` does this and stores an observation.

**Read next:** [Executing with LiteLLM](../docs/guides/09-litellm.md), [Execution](../docs/concepts/09-execution.md), [Local storage](../docs/guides/08-storage.md).

---

## How the examples fit together

```text
list_models        ->  ModelProfile            (what exists)
estimate_cost      ->  CostEstimate            (what it costs)
compare_models     ->  ComparisonReport        (how they stack up, with reasons)
constrained_select ->  SelectionResult         (one answer, given evidence)
pareto_frontier    ->  tradeoff set            (the options worth weighing)
benchmark_fake     ->  quality evidence        (where the evidence comes from)
execute_with_litellm -> ExecutionResult        (acting on the choice)
```

Evidence flows backwards through that chain: executing produces observations, benchmarking produces quality scores, and both feed the next selection.

## Conclusions

1. **Normalize early, decide late.** One `ModelProfile` shape means every later step is source-agnostic.
2. **Unknown is a first-class value.** Capabilities are tri-state, estimates carry `complete`, and missing evidence fails hard requirements. The library never fills a gap with a guess.
3. **Explain every outcome.** Comparison keeps reasons, selection keeps `assessments` and `rejection_counts`, and evidence keeps its source and sample count.
4. **Constrain, then rank, then (optionally) keep the tradeoff.** Hard filters, a named policy, and a Pareto frontier answer three different questions.
5. **Put a seam where the money and the network are.** A protocol-based `ExecutionBackend` is what lets benchmarks, tests, and demos run for free.
6. **Safe by default.** Dry-run execution, no payload storage, `Decimal` money, and no directories created at import time.

## Running everything

```bash
for f in list_models estimate_cost compare_models constrained_selection pareto_frontier benchmark_fake_backend execute_with_litellm; do
  echo "### $f"; uv run python examples/$f.py
done
```

For the full learning path, start with the [guides](../docs/guides/01-quickstart.md) in numeric order, and use the [concepts](../docs/concepts/01-models.md) pages when you want the reasoning behind a behavior.
