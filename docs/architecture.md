# Architecture

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

## Dependency direction

The dependency direction is domain-first: `catalogs`, `metrics`, `selection`, `storage`, and `execution` depend on provider-independent domain objects. The domain package does not import LiteLLM, Typer, Rich, HTTPX, SQLite, or provider SDKs.

## Why LiteLLM is a backend

LiteLLM normalizes one execution path, but it does not own analytics, ranking, or storage. Those responsibilities stay in Model Compass so request constraints, cost estimation, quality evidence, and observations remain consistent even if the backend changes.

## Why OpenRouter is authoritative for OpenRouter metadata

When a live OpenRouter catalog is available, it is the authoritative source for OpenRouter-specific metadata because it reflects the provider's current public catalog. LiteLLM metadata is useful as a secondary source, but it is treated as supplemental rather than primary when the sources disagree.

## Model vs endpoint

A `ModelProfile` describes a logical model. `ModelIdentity` names the model; `ModelEndpoint` describes how it can be reached. The project keeps them separate so a model can have more than one endpoint, and so catalog sources are not forced to invent endpoint data they never reported.

## Provider adapter boundaries

Provider adapters live at the catalog boundary. They fetch raw provider payloads, normalize them into the domain models, and preserve provenance. They do not decide selection policy, persist observations, or execute requests.

## Storage abstraction

Storage is an abstraction over prompt-free observations and benchmark records. The SQLite store is the default durable backend, while the in-memory store is used for tests and temporary workflows. Persistence happens only when a write operation occurs; importing the package does not create directories.

## Selection pipeline

1. build a `RequestProfile`
2. apply hard capability and constraint filters
3. attach quality, latency, reliability, and cost evidence
4. rank the eligible candidates under a named policy
5. retain the rejected candidates and their reasons for explanation

Hard filters always run before ranking. Missing data is visible and policy-controlled; it is never silently turned into a positive result.

## Benchmark pipeline

Benchmarks start from a JSONL dataset, evaluate each case deterministically when possible, and record reproducibility metadata plus quality evidence. Execution observations stay separate from benchmark-derived quality because they answer different questions.

## Configuration precedence

- CLI path options (`--data-dir`, `--cache-dir`, `--db`) override the platform defaults returned by `platformdirs`.
- Provider credentials are read from the environment only; the tool never stores them for you.
- `--config` is recorded by the CLI, but the current release does not load file-backed settings from it yet.

See [Configuration](configuration.md) for the current precedence rules in more detail.
