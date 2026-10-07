# Testing

Run the project checks with:

```bash
uv run pytest -m unit
uv run pytest -m mock
uv run pytest -m integration
uv run pytest -m "not live"
```

The mandatory test-suite command is the `not live` suite with coverage:

```bash
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
```

Live tests are opt-in and require the documented credentials or explicit acknowledgement for the relevant fixture or backend. They are excluded from the mandatory test command so the repository can be validated offline.

Run them explicitly with:

```bash
uv run pytest -m live
```

## Test taxonomy

- `unit` — isolated behavior, no network
- `mock` — mocked HTTP or LiteLLM calls
- `integration` — multiple components with temporary storage
- `live` — external APIs, opt-in only
- `slow` — long-running checks
