# Contributing to Model Compass

## Development Setup

```bash
git clone https://github.com/yuchdev/ModelCompass.git
cd ModelCompass
uv sync --all-groups
```

## Quality Gates

All PRs must pass:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
uv run mkdocs build --strict
uv build --out-dir .dist
```

## Test Categories

- `unit` — no network, no external services
- `mock` — HTTP mocked with respx
- `integration` — multi-component, temp storage
- `live` — external APIs, opt-in only
- `slow` — long-running tests

## Commit Style

Use conventional commits: `feat:`, `fix:`, `docs:`, `chore:`, `test:`, `refactor:`

## Security

- Never commit API keys
- Never log secrets
- Use `.env.example` for placeholder examples only
