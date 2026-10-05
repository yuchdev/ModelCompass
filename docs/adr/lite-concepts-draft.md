# Model Domain Concepts

The catalog layer normalizes provider metadata into immutable domain objects.

## Identity

- `ModelIdentity` separates provider/model identifiers from display names.
- `ModelEndpoint` captures endpoint-specific information.
- Canonical IDs are stable and provider-scoped (`provider:model_id`).

## Capabilities

Capabilities use tri-state support values:

- `SUPPORTED`
- `UNSUPPORTED`
- `UNKNOWN`

Missing source fields stay `UNKNOWN`; omitted fields are never inferred as unsupported.

## Aggregate

`ModelProfile` is the normalized aggregate consumed by application and selection layers. It stores:

- identity and endpoints
- capabilities
- pricing
- source/provenance metadata
- retrieval timestamp and raw references

# Pricing Concepts

All pricing values use `decimal.Decimal`.

## Components

`Pricing` stores normalized `PriceComponent` entries for known keys (prompt, completion, request, image, audio, web_search, internal_reasoning, input_cache_read, input_cache_write) and preserves unknown future keys.

## Overrides

`PricingOverride` supports conditional replacement by:

- prompt-token threshold (`prompt_tokens_gte`)
- UTC windows (`utc_window_start`, `utc_window_end`)

Rules:

- overrides can replace only some keys
- absent keys inherit current/base values
- later applicable overrides win per key
- clock injection enables deterministic boundary tests

## Provenance

`PricingProvenance` tracks per-key source and disagreements when sources conflict.

# Catalog Ingestion Guide

## Sources

- OpenRouter adapter (`/api/v1/models`) is authoritative for OpenRouter metadata/pricing.
- LiteLLM adapter is secondary/fallback metadata.

## Merge Rules

- OpenRouter pricing wins for fresh authoritative OpenRouter entries.
- LiteLLM can fill unknown capability fields.
- Conflicting values are retained in provenance metadata.
- Models are merged only by canonical identity, never by display name.

## Cache Behavior

OpenRouter snapshots are cached under platform cache paths with:

- cache format version
- fetched timestamp
- source URL
- raw payload
- normalized snapshot
- TTL metadata

Offline mode reads cache only; stale snapshots are explicitly marked.
Corrupt cache raises a clear error in offline mode and is ignored/refreshed in online mode.

