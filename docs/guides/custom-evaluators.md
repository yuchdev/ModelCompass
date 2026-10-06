# Custom evaluators

Every evaluator — built-in or custom — implements the same protocol:

```python
class Evaluator(Protocol):
    evaluator_id: str
    evaluator_version: str

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult: ...
```

`EvaluationResult` normalizes every evaluator's outcome to a `Decimal` score
in `[0, 1]`, an optional `passed` verdict (only set when a pass/fail notion
applies), the evaluator's id and version (for reproducibility), a short
`explanation`, and a `details` dict for anything evaluator-specific.

## Built-in deterministic evaluators

| `evaluator` id        | Expects on the case                                   | Notes |
|------------------------|--------------------------------------------------------|-------|
| `exact`                 | `expected_output`                                       | Case- and whitespace-sensitive. |
| `normalized_exact`       | `expected_output`                                        | Case-insensitive, whitespace-collapsed. |
| `regex`                  | `expected_output` (a pattern)                            | Full match (`re.fullmatch`); an invalid pattern raises `BenchmarkError`. |
| `contains_terms`         | `required_terms`                                          | Partial credit: score is the matched fraction. `evaluator_config`: `require_all` (default `True`), `case_sensitive` (default `False`). |
| `json_validity`          | nothing extra                                             | Scores syntactic JSON validity only, independent of shape. |
| `json_schema`            | `evaluator_config["schema"]` or `expected_json`           | With `schema`: validates a minimal JSON-Schema-like subset (`type`, `required`, `properties`, `items`) recursively. Without it: deep-equals `expected_json`. |
| `numeric_tolerance`      | `expected_output` and `numeric_tolerance`                 | Absolute by default; set `evaluator_config["relative"] = True` for a tolerance relative to `abs(expected)`. |

None of these need a heavy schema dependency — `json_schema` is a small,
hand-rolled recursive checker, sufficient for the structural checks fixtures
typically need.

## Writing a custom evaluator

```python
from decimal import Decimal

from model_compass.benchmarks import BenchmarkCase, EvaluationContext, EvaluationResult


class LengthBudgetEvaluator:
    evaluator_id = "length_budget"
    evaluator_version = "1.0.0"

    def evaluate(self, case: BenchmarkCase, response: str, context: EvaluationContext) -> EvaluationResult:
        limit = case.evaluator_config["max_characters"]
        passed = len(response) <= limit
        return EvaluationResult(
            score=Decimal(1) if passed else Decimal(0),
            passed=passed,
            evaluator_id=self.evaluator_id,
            evaluator_version=self.evaluator_version,
            explanation=f"{len(response)} characters against a budget of {limit}",
        )
```

Pass it to `run_benchmark` or `evaluate_offline` via `custom_evaluators`,
keyed by the id a case's `evaluator` field will use:

```python
await run_benchmark(dataset, models, backend=backend, custom_evaluators={"length_budget": LengthBudgetEvaluator()})
```

A custom evaluator takes precedence over a built-in one with the same id
(`resolve_evaluator` checks `custom_evaluators` first), so you can also
override a built-in's behavior for a specific run. An evaluator can be
`async def evaluate(...)` instead of synchronous; the runner awaits it if so.

## The optional LLM judge

`LLMJudgeEvaluator` is a separate, **opt-in** evaluator — a dataset using
`evaluator="llm_judge"` does nothing unless the caller explicitly passes an
`llm_judge=LLMJudgeEvaluator(...)` instance to `run_benchmark`. If a judge
case runs without one configured, it is recorded as a failed case
(`error_category="evaluation_failed"`), never silently skipped or scored.

```python
from model_compass.benchmarks import JudgeConfig, LLMJudgeEvaluator
from model_compass.execution import LiteLLMBackend

judge = LLMJudgeEvaluator(
    backend=LiteLLMBackend(),
    config=JudgeConfig(
        judge_model_id="openrouter/a-different-strong-model",
        prompt_version="v1",
    ),
)
outcome = await run_benchmark(dataset, candidate_models, backend=LiteLLMBackend(), llm_judge=judge)
```

`JudgeConfig` requires an explicit `judge_model_id` and `prompt_version` —
nothing about the judge is inferred. The evaluator refuses outright
(`JudgeEvaluationError`) if the candidate model being scored is the same as
the judge model, so a model is never asked to grade itself. The judge's
prompt template and version are recorded on every `EvaluationResult`
(`evaluator_version` is the configured `prompt_version`), and its own
execution cost is recorded separately in `details["judge_cost_usd"]` — never
merged into the candidate model's cost.

**Judge failure never fabricates a score.** A backend error, non-JSON
output, a JSON object missing a `score` field, or a score outside `[0, 1]`
all raise `JudgeEvaluationError`, which `run_benchmark` turns into a failed
`BenchmarkResult` (`score=None`, `error_category="evaluation_failed"`) rather
than a fake `0`.

### Bias and non-independence

An LLM judge is not an independent, ground-truth oracle:

- It inherits the judge model's own biases (verbosity preference, stylistic
  preferences, position bias when comparing multiple candidates, and
  systematic blind spots the judge model shares with similar candidate
  models).
- A judge from the same model family as a candidate tends to score that
  candidate's outputs more favorably than an unrelated judge would — this is
  why the evaluator refuses to let a model judge itself, but it cannot
  detect family-level relatedness.
- `temperature` defaults to `0` for deterministic-ish grading, but LLM
  outputs are not guaranteed bit-for-bit reproducible even at `temperature=0`
  across provider versions.
- Treat LLM-judge scores as a cheaper, noisier proxy for human judgment, not
  a replacement for deterministic evaluators or human review on anything
  consequential. Where possible, prefer a deterministic evaluator; reserve
  the judge for qualities (tone, helpfulness, coherence) that genuinely
  resist exact-match-style scoring.

The deterministic evaluator suite above works with no API key and no
network access; the judge is the only evaluator in this package that makes a
provider call.
