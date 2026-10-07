# Model Compass

> **Warning:** Model recommendations produced by this tool are evidence-based estimates, not guarantees. Always validate model choices for your specific workload.

Model Compass is a Python library and CLI for request-aware LLM model analytics: it ingests model catalogs, estimates request cost, compares candidates, applies transparent selection policies, runs reproducible benchmarks, and records prompt-free execution observations.

## Why this project

LLM model choice is usually explained with one number, one benchmark, or one provider's marketing page. Model Compass keeps the inputs separate so you can see prices, request requirements, quality evidence, latency, reliability, and the tradeoffs between them.

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

## Status

Alpha. The core API is stable enough for experimentation and internal tooling, but the project still expects careful validation for production use.

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

## 60-second library example

```python
from datetime import UTC, datetime
from decimal import Decimal

from model_compass import (
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
    RequestProfile,
    SelectionPolicy,
    analytics,
)

request = RequestProfile(
    task="summarization",
    explicit_input_tokens=2_000,
    expected_output_tokens=500,
    max_cost_usd=Decimal("0.02"),
)
profiles = [
    ModelProfile(
        identity=ModelIdentity(provider="demo", model_id="small", canonical_id="demo:small"),
        capabilities=ModelCapabilities(input_modalities=("text",), output_modalities=("text",)),
        pricing=Pricing(components={
            "prompt": PriceComponent(key="prompt", amount=Decimal("0.000001")),
            "completion": PriceComponent(key="completion", amount=Decimal("0.000002")),
        }),
        retrieved_at=datetime.now(UTC),
    ),
    ModelProfile(
        identity=ModelIdentity(provider="demo", model_id="large", canonical_id="demo:large"),
        capabilities=ModelCapabilities(input_modalities=("text",), output_modalities=("text",)),
        pricing=Pricing(components={
            "prompt": PriceComponent(key="prompt", amount=Decimal("0.000003")),
            "completion": PriceComponent(key="completion", amount=Decimal("0.000006")),
        }),
        retrieved_at=datetime.now(UTC),
    ),
]
choice = analytics.select(profiles, request, policy=SelectionPolicy.CHEAPEST)
print(choice.selected.model_id if choice.selected else "no selection")
```

See the [quickstart guide](docs/guides/quickstart.md) for a fuller offline example.

## Architecture diagram

```text
CLI / application facade
          |
          v
request profile -> estimation -> selection / pareto -> explanations
          |             |              |
          v             v              v
   catalogs        metrics / storage   execution
OpenRouter         observations        LiteLLM backend
and LiteLLM        and benchmarks      or another backend
```

## Model-selection philosophy

Model Compass filters out hard violations first, then ranks only the surviving candidates. It keeps missing data visible instead of inventing certainty, and it treats cost, quality, reliability, and latency as separate concerns rather than collapsing them into one score.

## Data/privacy note

Execution observations intentionally omit prompt and response bodies by default. API keys are read from the environment and never stored by the library. Use the `PayloadPolicy.FULL` options only when you explicitly want to retain raw content.

## Testing

```bash
uv run pytest -m unit
uv run pytest -m mock
uv run pytest -m integration
uv run pytest -m "not live"
```

Live tests are opt-in and require the documented credentials or explicit acknowledgements in the test environment.

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening a PR. Documentation changes are part of the product here, not an afterthought.

## License

MIT. See [LICENSE](LICENSE).

## Docs

- [Documentation home](docs/index.md)
- [Architecture](docs/architecture.md)
- [Configuration](docs/configuration.md)
- [CLI](docs/cli.md)
- [Testing](docs/testing.md)
- [API reference](docs/reference/api.md)
