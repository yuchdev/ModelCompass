# 02. Catalogs

**Level:** beginner · **Time:** 10 minutes · **Needs:** [01. Quickstart](01-quickstart.md); network for the first refresh

In [01. Quickstart](01-quickstart.md) you wrote a model profile by hand. In this tutorial you will load real ones from the OpenRouter and LiteLLM catalogs, and learn how to judge whether the data is fresh enough to trust.

## Step 1: Refresh the catalog

```bash
uv run model-compass catalog refresh
```

This fetches OpenRouter's `/api/v1/models`, normalizes each entry into a `ModelProfile`, and stores the raw payload in the cache directory. The report lists each source and any warnings.

## Step 2: Browse what you fetched

```bash
uv run model-compass models list --limit 5
uv run model-compass models --format json
```

`models list` filters by capability, source, and price. `models show` prints every normalized field for one model.

## Step 3: Read it offline

Add `--offline` to use only the cached snapshot and make no network request:

```bash
uv run model-compass models --offline --format json
```

[03. Offline use](03-offline-use.md) covers this mode in depth.

## Step 4: Understand where values come from

- OpenRouter is the primary source and is authoritative for OpenRouter pricing.
- LiteLLM's bundled metadata fills in fields OpenRouter leaves unknown. `analytics.catalog.refresh()` merges the two by default.
- A field the sources do not report stays `UNKNOWN`. It is never guessed, and it never satisfies a hard requirement.

## Step 5: Check freshness before you rely on a price

Catalog values change over time. Look at the retrieval timestamp and the stale flag before trusting a price. If a refresh fails but an older cache exists, Model Compass serves the cache and marks it stale instead of failing silently.

## What you learned

- How to refresh and browse the catalog from the CLI.
- That OpenRouter wins merge conflicts unless its value is unknown.
- That timestamps and stale status are part of the data, so check them.

## Next

[03. Offline use](03-offline-use.md) shows how to work without live access.
