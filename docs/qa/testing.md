# Testing

## Test Categories

| Marker | Description | Network? | Storage? |
|--------|-------------|----------|----------|
| `unit` | Single class/function in isolation | No | No |
| `mock` | Mocked HTTP (respx) or LiteLLM | No | No |
| `integration` | Multi-component, temp SQLite | No | Temp |
| `live` | Real external APIs | Yes | Optional |
| `slow` | Long-running | Optional | Optional |

## Running Tests

```bash
# All non-live tests (mandatory CI gate)
uv run pytest -m "not live"

# With coverage
uv run pytest -m "not live" --cov=model_analytics --cov-branch --cov-fail-under=90

# Live tests (requires API keys)
uv run pytest -m live
```

## Coverage Policy

- Branch coverage enabled
- Target: >=90% for production code
- Exclusions allowed only for: `TYPE_CHECKING` blocks, defensive `AssertionError`, platform wrappers, documented optional-import guards
