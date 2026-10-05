# Testing

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
uv run mkdocs build --strict
uv build
```

Unit tests cover domain/selection behavior without network calls. Mock tests
exercise provider adapters with mocked HTTP or LiteLLM calls. Integration tests
use temporary SQLite files. `live` tests are opt-in and excluded from the
mandatory test command. See the [testing taxonomy](qa/testing.md).
