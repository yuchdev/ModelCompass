# Catalogs

The OpenRouter adapter fetches and normalizes `/api/v1/models`, preserving raw
catalog references and cache provenance. A cached snapshot can be read offline:

```bash
model-compass models --offline --format json
```

OpenRouter is authoritative for OpenRouter catalog pricing. LiteLLM metadata
can supplement catalog fields using `analytics.catalog.refresh()`'s default
merge behavior. Catalog values are time-sensitive; check retrieval timestamps
and stale status before relying on them.
