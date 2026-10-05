# Security

Threat models, security review outputs, and posture documentation for ModelCompass.

The `security-auditor` agent owns this directory. Every change touching auth,
secrets, external integrations, or untrusted-input ingestion triggers a security
review whose output is stored here.

## Naming convention

`threat-model-<scope>.md` for threat models, `review-<scope>-<YYYY-MM-DD>.md`
for point-in-time reviews.

## What a threat model must contain

1. **Scope** - which components and trust boundaries are in scope.
2. **Assets** - what secrets, PII, and data are handled.
3. **Threat actors** - attacker profiles considered.
4. **STRIDE analysis** - Spoofing, Tampering, Repudiation, Info Disclosure, DoS, Elevation.
5. **Mitigations** - existing controls and open gaps.
6. **Verdict** - CRITICAL (merge blocked) / HIGH / MEDIUM / LOW / INFO.

## Security rules (non-negotiable)

- Never log secrets; rely on this project's log-redaction mechanism (if any)
  and verify it covers new sinks.
- Never hard-code credentials. Read from settings/env.
- Treat all untrusted external input as sensitive - no unredacted raw input
  in logs, exceptions, stored reports, or API error bodies.
- Untrusted input must never reach a shell, SQL string, `eval`, or an AI
  prompt without sanitization/parameterization.

> **SME REVIEW NEEDED (AI-drafted - verify before relying on this):**
>
> ## Initial threat model - catalog ingestion and request analysis (alpha)
>
> **Scope.** A local, single-user library and CLI (`model-compass`). In scope:
> - `catalogs/openrouter.py`: outbound HTTPS to `https://openrouter.ai/api/v1/models` via httpx, plus the on-disk JSON cache.
> - `catalogs/litellm.py`: reads `litellm.model_cost`.
> - `metrics/` and `selection/`: pure analysis of caller-supplied request descriptions.
> - `cli/app.py`: `version` and `doctor`.
>
> There is no server, auth layer, or inbound network surface. `storage/` (planned SQLite) and `execution/` (planned LiteLLM calls) are empty stubs and out of scope until implemented. Trust boundaries are:
> 1. the OpenRouter HTTP response;
> 2. the cache file in the user cache dir;
> 3. the installed LiteLLM package's metadata;
> 4. the calling application's prompts, messages, tools, and schemas.
>
> **Assets.**
> - `OPENROUTER_API_KEY`, sent as `Authorization: Bearer` when supplied. `OPENAI_API_KEY` and `ANTHROPIC_API_KEY` are listed in `.env.example` for future use.
> - Caller prompt and message content, possibly proprietary.
> - The integrity of pricing and capability data, since users budget and select models from `CostEstimate`/`EligibilityResult`.
> - `openrouter_catalog.json` (raw payload plus normalized snapshot).
>
> **Threat actors.** A compromised or misbehaving upstream catalog (OpenRouter or a malicious LiteLLM release), a local process or user able to write the cache directory, and a caller passing hostile or oversized request content. A network MITM is mitigated by TLS to the default base URL.
>
> **STRIDE.**
> - *Spoofing*: a caller-supplied `base_url` on `OpenRouterCatalogAdapter` would receive the Bearer key. Only trusted URLs should be passed.
> - *Tampering*:
>   - A modified cache file is loaded by `_load_cache` and trusted after `CatalogSnapshot.model_validate`. Pydantic enforces non-negative `Decimal` prices, but not plausibility.
>   - A tampered upstream payload can mark capabilities `SUPPORTED` or set prices to zero, producing false recommendations.
>   - Unrecognized keys flow into `extra_metadata` and override `metadata` unchecked.
> - *Repudiation*: limited relevance. `CatalogSource`, `PricingProvenance`, and merge `conflicts` record which source supplied each value.
> - *Information disclosure*:
>   - The API key must never be written to the cache, exception text, or `doctor` output. Currently `CatalogFetchError` messages include only the URL and status.
>   - Request content must not be echoed into `RequestProfile.metadata`, `notes`, or `assumptions`, or into `ComparisonReport.to_json()`.
>   - No logging exists in `src/`, so there is no redaction layer to rely on.
> - *Denial of service*:
>   - An oversized catalog response or cache file is parsed fully in memory with no size cap. httpx timeouts are bounded (`connect=5`, `read=15`).
>   - Large `messages` lists are `json.dumps`-ed and passed to `litellm.token_counter` without limits.
> - *Elevation of privilege*: no shell, SQL, or `eval` sinks exist today. Re-assess when the SQLite `storage/` lands, which needs parameterized queries.
>
> **Mitigations in place.**
> - API keys come only from the environment and are never persisted (README, `AGENTS.md`).
> - Cache writes are atomic (temp file + `replace`).
> - A corrupt cache raises `CatalogCacheError` in offline mode and is ignored online.
> - Malformed catalog entries are skipped with `parse_warnings`.
> - `UNKNOWN`/incomplete data is rejected by default (`MissingDataPolicy.REJECT`).
> - Mandatory tests use no network or secrets.
>
> **Open gaps.**
> - No response or cache size limit.
> - No integrity check on the cache file.
> - No allow-list for `base_url` before attaching the key.
> - The cache directory is created with default permissions.
>
> **Verdict (draft): LOW** for the current alpha surface. Re-review is required when `storage/` or `execution/` is implemented, because execution will transmit request content and keys to providers.
