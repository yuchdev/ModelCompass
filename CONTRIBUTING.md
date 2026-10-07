# Contributing to Model Compass

## Setup

```bash
git clone https://github.com/yuchdev/ModelCompass.git
cd ModelCompass
uv sync --all-groups
```

## Branch and PR expectations

- Keep changes small and focused.
- Use conventional commits (`feat:`, `fix:`, `docs:`, `test:`, `chore:`).
- Include documentation updates whenever public behavior changes.
- Prefer tests that demonstrate the new behavior rather than broad rewrites.

## Issue workflow

- Start from the issue requirements and preserve existing public APIs unless the issue says otherwise.
- Validate the change locally before asking for review.
- Keep the changelog in `Unreleased` up to date with user-facing changes.

## Quality gates

All PRs must pass:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
uv run mkdocs build --strict
uv build --out-dir .dist
```

## Test taxonomy

- `unit` — no network, no external services
- `mock` — HTTP mocked with respx
- `integration` — multi-component, temp storage
- `live` — external APIs, opt-in only
- `slow` — long-running tests

## Architecture rules

- `domain` stays provider-agnostic.
- `catalogs`, `metrics`, `selection`, `storage`, and `execution` depend on the domain layer, not the other way around.
- The CLI talks to the public application/service API.
- Do not add LiteLLM, Typer, Rich, SQLite, or provider SDK imports to the domain layer.

## Extending the project

- **Provider adapter**: keep raw payload handling inside the adapter layer and normalize into domain models.
- **Metric**: preserve the metric source, unit, and missing-data behavior in the public result model.
- **Selector policy**: keep hard filters separate from ranking and preserve deterministic tie-breaks.
- **Evaluator**: make the evaluator deterministic when possible, or document its caveats clearly.

## Documentation requirement

Every public feature addition should come with docs, examples, or both. If a user can invoke it, a newcomer should be able to discover it without reading the source.

## Release process

No automated release workflow is configured. Maintainers should:

1. Bump the version in `pyproject.toml` and move the completed `Unreleased` entries in `CHANGELOG.md` to a dated version heading.
2. Run the quality gates above and build the distributions with `uv build --out-dir .dist`.
3. Create and push a `vX.Y.Z` tag, then create the matching GitHub release using the changelog entry as its notes.
4. Publish the built distributions to the project's package index, if a package release is intended.

## Security

- Never commit API keys
- Never log secrets
- Use `.env.example` for placeholder examples only
