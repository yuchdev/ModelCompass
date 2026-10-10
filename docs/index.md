# Model Compass

Model Compass is a Python library and CLI for request-aware LLM model analytics, comparison, and selection.

It helps you answer questions such as:

- which model is cheapest for a request;
- whether a model is eligible before ranking;
- how quality evidence was obtained;
- what the estimated cost means;
- how to run benchmarks and keep their evidence separate from execution observations.

## Start here

- [Quickstart](guides/01-quickstart.md)
- [Configuration](configuration.md)
- [Selection model](concepts/06-selection.md)
- [Benchmarks](guides/10-benchmarks.md)
- [Testing](testing.md)
- [API reference](reference/api.md)

## What is included

- OpenRouter and LiteLLM catalog ingestion
- Decimal-based pricing and cost estimation
- Capability matching and transparent selection policies
- Pareto analysis for cost / quality / latency / reliability tradeoffs
- Benchmark datasets, deterministic evaluators, and optional LLM judging
- Prompt-free local execution observations

## Design principles

- prices and calculated costs use `decimal.Decimal`
- missing capability or evidence data stays explicit
- selection returns reasons and evidence, not just a model id
- quality evidence is task-specific
- prompt and response bodies are not persisted unless you opt in
- benchmark and execution data are stored separately
