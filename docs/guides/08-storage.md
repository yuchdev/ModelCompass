# 08. Local storage

**Level:** intermediate · **Time:** 15 minutes · **Needs:** [06. Analytics and selection](06-analytics.md)

Observations and benchmark results need somewhere to live. In this tutorial you will pick a store, record and summarize data, move it between machines as JSONL, and choose a safe payload policy.

## Step 1: Pick a store

`SQLiteObservationStore` and `InMemoryObservationStore` implement the `ObservationStore` protocol. The application facade creates a SQLite store object without opening a database; the file and its parent directory are created only when a storage operation first needs them.

- By default, SQLite uses `observations.sqlite3` in the platform user data directory from `platformdirs`.
- Pass an explicit file path for a separate store, or `:memory:` for an ephemeral SQLite database.
- `InMemoryObservationStore` suits tests and applications that do not want persistence.

## Step 2: Record and summarize

```python
from model_compass.domain import Observation
from model_compass.storage import InMemoryObservationStore, SQLiteObservationStore

store = SQLiteObservationStore()  # no file created until an operation is used
store.record_observation(Observation(model_id="provider:model", success=True))
summary = store.summarize_model("provider:model", min_samples=1)

ephemeral = InMemoryObservationStore()
```

## Step 3: Filter by time and scope

Storage methods filter observations by model, task, endpoint, a UTC timestamp, or a recent duration. `summarize_model` and `summarize_task` accept the same time-window filters. Naive timestamps are rejected.

## Step 4: Export and import

`export_jsonl()` returns deterministic JSON Lines containing observations and benchmark results.

- Each record carries a schema version.
- Decimal values are strings and timestamps use ISO 8601 UTC.
- `import_jsonl(content, deduplicate=True)` validates each record and skips IDs already present.
- Invalid input raises `ImportRecordError` with the source line number.
- Export and import do not include benchmark-run configuration or normalized quality evidence.

## Step 5: Choose a payload policy

The default `PayloadPolicy.NONE` does not persist raw prompts or responses. `HASH_ONLY` stores a SHA-256 fingerprint of the request prompt when available while still discarding raw payloads. Hashes are not anonymization for predictable inputs.

**Warning:** `PayloadPolicy.FULL` explicitly persists raw prompt and response data. This can store sensitive user content in the SQLite database, its backups, and JSONL exports. Enable it only after assessing access controls, retention, export handling, and backup handling. Do not put secrets or raw prompts in user-controlled metadata; metadata is stored as supplied.

## What you learned

- That nothing touches disk until you ask it to.
- How to filter, summarize, export, and import observations.
- Why `NONE` is the safe default for payloads.

## Next

[09. Executing with LiteLLM](09-litellm.md) produces real observations by calling models.
