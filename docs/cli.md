# Command-line interface

The `model-compass` CLI exposes catalog, estimation, comparison, selection,
observation, and benchmark features. Commands are scriptable with `--format
json`; complex JSON responses include `schema_version: 1`, a command name, and
Decimal values encoded as strings.

## Quickstart

```bash
model-compass --help
model-compass catalog refresh --source all
model-compass models list --modality text --limit 20
model-compass models show openrouter:openai/gpt-4o-mini
model-compass estimate --model openrouter:openai/gpt-4o-mini \
  --input-tokens 1000 --expected-output-tokens 500 --format json
model-compass select --objective cheapest --input-tokens 1000 \
  --expected-output-tokens 500 --max-cost 0.05
```

Catalog-backed commands fetch OpenRouter's public catalog by default. Use
`--offline` where offered to require cached catalog data. `catalog refresh
--source` accepts `openrouter`, `litellm`, or `all`.

## Command groups

### Configuration and diagnostics

`config show` reports effective paths and the names (never values) of detected
provider credential variables. `config paths` prints paths without creating
directories. `--config PATH` records the selected configuration-file path;
the current library configuration has no file settings to load. `doctor`
reports Python, platform, LiteLLM availability, and paths.

Global path and diagnostic options are `--config PATH`, `--data-dir PATH`,
`--cache-dir PATH`, `--db PATH`, `--debug`, and `--no-color`. They are placed
before the command:

```bash
model-compass --data-dir ./data --cache-dir ./cache --db ./data/analytics.sqlite3 db status
```

### Catalog and models

```bash
model-compass catalog refresh --source openrouter [--force] [--offline]
model-compass catalog sources --format json
model-compass catalog status
model-compass models list --gateway openrouter --minimum-context 32000
model-compass models list --modality vision --tools --structured-output --reasoning
model-compass models list --free-only --search llama --limit 10 --format json
model-compass models show openrouter:openai/gpt-4o-mini
```

The list output uses compact capability and pricing columns. `models show`
returns the complete normalized profile, pricing overrides, provenance, source
freshness, and stored observation summary.

### Estimate, compare, select, and Pareto

`estimate` accepts exactly one prompt source: `--prompt TEXT`, `--prompt-file
PATH`, explicit `--input-tokens`, or explicit `--stdin`. It never reads stdin
implicitly. Give `--model ID` or `--filter TEXT` to choose one or more models.
Capability requirements can further filter estimates with `--input-modality`,
`--output-modality`, `--minimum-context`, `--require-tools`,
`--require-structured-output`, and `--require-reasoning`.

`compare` reports eligibility, estimates, ranking, and rejection reasons.
`--allow-model`, `--block-model`, `--sort`, and `--limit` narrow or order the
candidate set. `select` supports the objectives `cheapest`, `best`, `fastest`,
`most-reliable`, and `cost-efficient`, plus quality, cost, latency, reliability,
capability, context, and model allow/block constraints. Selection does not
execute a model.

```bash
model-compass compare --task code-review --input-tokens 12000 --sort cheapest --limit 25
model-compass select --objective cost-efficient --min-quality 0.8 --max-cost 0.05
model-compass pareto --objective quality:max --objective cost:min --format json
model-compass pareto --include-dominated
```

Pareto defaults to quality maximization and cost minimization. Add repeatable
`--objective DIMENSION:min|max` values for latency and reliability.

### Observations and storage

```bash
model-compass observations stats --model openrouter:openai/gpt-4o-mini \
  --task summarization --since 2026-01-01T00:00:00Z --provider openai
model-compass observations export --output observations.jsonl
model-compass observations import observations.jsonl
model-compass db status
model-compass db vacuum
```

Observation export/import uses the versioned JSONL storage format. Import
validates records and needs no interactive confirmation; `--deduplicate` skips
records already present in the selected database.

### Benchmarks

`benchmark run` is an explicit live side effect: it sends provider requests and
may incur charges. It requires `--acknowledge-live`, at least one explicit
`--model`, and a dataset. Set a budget and concurrency deliberately.

```bash
model-compass benchmark run --dataset dataset.jsonl --model openai/model \
  --repetitions 2 --concurrency 1 --max-cost 1.00 --acknowledge-live
model-compass benchmark list
model-compass benchmark show RUN_ID
model-compass benchmark export --run-id RUN_ID --output run.json
```

Repeated live results are persisted as one case/model average for each available
numeric measurement; its metadata retains the individual repetition results.

The backward-compatible bare form `benchmark --dataset FILE --outputs FILE
--model MODEL` evaluates saved outputs offline. Pass `--record` to store its
quality evidence.

The separate `run` command is also an explicit side effect. Supply
`--stdin` to opt into reading a prompt from stdin:

```bash
printf 'Summarize this text' | model-compass run --model openai/model --stdin
```

## Output and exit codes

Use `--format table|json` on commands that produce structured results. Tables
use Rich; `--no-color` disables styling, and non-terminal output is uncolored
automatically. Errors are concise by default; `--debug` includes a traceback.

| Code | Meaning |
| --- | --- |
| 0 | Success |
| 2 | CLI usage, configuration, or invalid model/request |
| 3 | No eligible model or no matching candidates |
| 4 | Catalog/provider failure |
| 5 | Execution or benchmark failure |
| 6 | Storage failure |

## Shell completion

Typer provides shell completion. Install it using the instructions printed by
`model-compass --install-completion`; use `model-compass --show-completion` to
inspect the generated script before installing.
