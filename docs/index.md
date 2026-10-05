# Model Compass

Model Compass is a Python library and CLI for request-aware LLM model catalog
analysis, cost estimation, empirical metrics, model selection, and execution.
It uses LiteLLM for normalized execution, while owning its request constraints,
selection policies, explanations, and Pareto analysis.

## Quick start

Install the project and run the CLI:

```bash
uv sync --all-groups
uv run model-compass --help
```

Read the [analytics guide](guides/analytics.md) for selecting a model from an
explicit request profile. Catalog-backed commands may fetch OpenRouter's public
catalog; pass `--offline` to use only a cached snapshot.

## Design principles

- Prices and calculated costs use `decimal.Decimal`.
- Unknown capability and evidence data is kept distinct from unsupported data.
- Selection returns eligibility reasons and the evidence used.
- Quality summaries only use evidence matching the requested task.
- Prompt and message bodies are not written to the observation database.
- Core selection and benchmark evaluation are deterministic and offline.

See [Architecture](architecture.md), [Pricing](concepts/pricing.md), and
[Testing](testing.md) for details.
