# Quickstart

This is the shortest path from installation to a useful result.

## 1. Install

```bash
uv sync --all-groups
uv run model-compass --help
```

## 2. Inspect the CLI

```bash
uv run model-compass doctor
uv run model-compass config paths
```

`doctor` tells you whether LiteLLM is available and where the default paths point. `config paths` shows the effective data, cache, and database locations without creating them.

## 3. Use the library offline

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
    task='summarization',
    explicit_input_tokens=2_000,
    expected_output_tokens=500,
    max_cost_usd=Decimal('0.02'),
)
profile = ModelProfile(
    identity=ModelIdentity(provider='demo', model_id='small', canonical_id='demo:small'),
    capabilities=ModelCapabilities(input_modalities=('text',), output_modalities=('text',)),
    pricing=Pricing(components={
        'prompt': PriceComponent(key='prompt', amount=Decimal('0.000001')),
        'completion': PriceComponent(key='completion', amount=Decimal('0.000002')),
    }),
    retrieved_at=datetime.now(UTC),
)
result = analytics.select([profile], request, policy=SelectionPolicy.CHEAPEST)
print(result.selected.model_id if result.selected else 'no eligible model')
```

The example stays offline: it uses synthetic profiles and a local selection call. For catalog-backed workflows, see the [catalog guide](catalogs.md) and [offline use guide](offline-use.md).
