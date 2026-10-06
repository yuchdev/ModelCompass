# Model Compass

> **Warning:** Model recommendations produced by this tool are evidence-based estimates, not guarantees. Always validate model choices for your specific workload.

A production-quality Python library and CLI for **request-aware LLM model analytics, comparison, and selection**.

## What it does

Model Compass provides:

- OpenRouter and LiteLLM catalog ingestion and normalization
- Pricing normalization and cost estimation (with Decimal precision)
- Request requirements and capability matching
- Quality evidence and benchmark results
- Latency and reliability observations
- Constrained model selection (cheapest/best/fastest/most-reliable/cost-efficient)
- Pareto-frontier analysis
- Explanations of why a model was selected or rejected
- Local persistent analytics storage (SQLite)
- CLI access to all stable capabilities

## Features

- OpenRouter model catalog ingestion, normalized pricing, and cached offline reads
- LiteLLM metadata as a secondary catalog source
- Typed request profiles and Decimal-based token cost estimates
- Deterministic cheapest, best, fastest, most-reliable, and cost-efficient selection
- Hard capability, cost, quality, and latency constraints with rejection reasons
- Exact-task empirical metrics and Pareto-frontier analysis
- SQLite observation storage that excludes prompt and message bodies
- LiteLLM execution and deterministic exact/regex/JSON benchmark evaluation

## Install from source

```bash
git clone https://github.com/yuchdev/ModelCompass.git
cd ModelCompass
uv sync --all-groups
uv run model-compass --help
```

## Development setup

```bash
# Install uv (if not already installed)
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/yuchdev/ModelCompass.git
cd ModelCompass
uv sync --all-groups
```

## Quality commands

```bash
# Format check
uv run ruff format --check .

# Lint
uv run ruff check .

# Type check
uv run mypy src tests

# Tests (no live API calls)
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90

# Docs build
uv run mkdocs build --strict

# Package build
uv build --out-dir .dist
```

## CLI

```bash
# Show help, list models, and inspect model details
model-compass --help
model-compass models list --modality text --limit 20
model-compass models show openrouter:openai/gpt-4o-mini

# Estimate request cost
model-compass estimate --model openrouter:openai/gpt-4o-mini \
  --input-tokens 1000 --expected-output-tokens 500 --format json

# Compare or select models without executing them
model-compass compare --task code_review --input-tokens 40000 --sort cheapest
model-compass select --task code_review --input-tokens 40000 \
  --expected-output-tokens 2000 --require-tools --max-cost 0.05 --objective cheapest

# Run live benchmarks only with an explicit acknowledgement
model-compass benchmark run --dataset dataset.jsonl --model openai/gpt-4o-mini \
  --max-cost 1.00 --acknowledge-live

# Inspect local observations
model-compass observations stats --task summarization --format json
```

Catalog-backed commands use OpenRouter's public model list; use `--offline` to
require a previously cached snapshot. See the [CLI guide](docs/cli.md) for
command groups, global path overrides, JSON output, and exit codes.

## Configuration

Copy `.env.example` to `.env` and fill in your API keys:

```bash
cp .env.example .env
```

**Note:** API keys are read from environment variables only. They are never persisted by this tool.

The initial implementation recognizes `OPENROUTER_API_KEY`, `OPENAI_API_KEY`,
and `ANTHROPIC_API_KEY` through the LiteLLM/provider integrations. They are
optional for offline analytics and catalog access.

## Library example

```python
from decimal import Decimal

from model_compass import RequestProfile, SelectionPolicy, analytics

request = RequestProfile(
    task="summarization",
    explicit_input_tokens=2_000,
    expected_output_tokens=500,
    max_cost_usd=Decimal("0.02"),
)
snapshot = analytics.catalog.refresh(include_litellm=False)
choice = analytics.select(list(snapshot.models.values()), request, policy=SelectionPolicy.CHEAPEST)
if choice.selected is not None:
    print(choice.selected.model_id, choice.selected.reasons)
```

See the [analytics guide](https://yuchdev.github.io/ModelCompass/guides/analytics/)
for request profiles, missing-data behavior, and observation examples.
