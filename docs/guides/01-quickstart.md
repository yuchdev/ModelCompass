# 01. Quickstart

**Level:** beginner · **Time:** 5 minutes · **Needs:** `uv`, no network, no API keys

In this tutorial you will install Model Compass, check that your environment is healthy, and pick the cheapest model from a hand-made list, all offline.

## Step 1: Install

```bash
uv sync --all-groups
uv run model-compass --help
```

If the help text lists commands such as `doctor`, `compare`, and `select`, the install worked.

## Step 2: Inspect your environment

```bash
uv run model-compass doctor
uv run model-compass config paths
```

`doctor` tells you whether LiteLLM is available and where the default paths point. `config paths` shows the effective data, cache, and database locations without creating them. Nothing is written to disk yet.

## Step 3: Describe what you need

A `RequestProfile` says what a request looks like: its task, how many tokens go in and come out, and any hard limits.

```python
from decimal import Decimal

from model_compass import RequestProfile

request = RequestProfile(
    task="summarization",
    explicit_input_tokens=2_000,
    expected_output_tokens=500,
    max_cost_usd=Decimal("0.02"),
)
```

Money is always a `Decimal`, never a `float`, so costs stay exact.

## Step 4: Describe a model

Normally profiles come from a catalog (see [Catalogs](02-catalogs.md)). For a first run, build one by hand. Prices are per token.

```python
from datetime import UTC, datetime

from model_compass.domain import (
    ModelCapabilities,
    ModelIdentity,
    ModelProfile,
    PriceComponent,
    Pricing,
)

profile = ModelProfile(
    identity=ModelIdentity(provider="demo", model_id="small", canonical_id="demo:small"),
    capabilities=ModelCapabilities(input_modalities=("text",), output_modalities=("text",)),
    pricing=Pricing(
        components={
            "prompt": PriceComponent(key="prompt", amount=Decimal("0.000001")),
            "completion": PriceComponent(key="completion", amount=Decimal("0.000002")),
        }
    ),
    retrieved_at=datetime.now(UTC),
)
```

## Step 5: Select a model

```python
from model_compass import SelectionPolicy, analytics

result = analytics.select([profile], request, policy=SelectionPolicy.CHEAPEST)
print(result.selected.model_id if result.selected else "no eligible model")
```

You should see `small`. The call is local: it filters out models that break your limits, estimates cost for the rest, and ranks them.

## What you learned

- How to verify an install with `doctor`.
- That a request (`RequestProfile`) and a model (`ModelProfile`) are the two inputs to every decision.
- That `analytics.select` needs no network when you supply the profiles.

## Next

[02. Catalogs](02-catalogs.md) shows how to get real model profiles instead of hand-made ones.
