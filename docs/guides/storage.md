# Local analytics storage

`SQLiteObservationStore` and `InMemoryObservationStore` implement the
`ObservationStore` protocol. The application facade creates a SQLite store object
without opening a database; the database file and its parent directory are created
only when a storage operation is first requested.

By default, SQLite uses `observations.sqlite3` in the platform user data directory
provided by `platformdirs`. Pass an explicit file path for a separate store or
`:memory:` for an ephemeral SQLite database. `InMemoryObservationStore` is useful
for tests and applications that do not want persistence.

```python
from model_compass.domain import Observation
from model_compass.storage import InMemoryObservationStore, SQLiteObservationStore

store = SQLiteObservationStore()  # no file created until an operation is used
store.record_observation(Observation(model_id="provider:model", success=True))
summary = store.summarize_model("provider:model", min_samples=1)

ephemeral = InMemoryObservationStore()
```

Storage methods support filtering observations by model, task, endpoint, a UTC
timestamp, or a recent duration. `summarize_model` and `summarize_task` accept the
same time-window filters. Naive timestamps are rejected.

## Export and import

`export_jsonl()` returns deterministic JSON Lines containing observations and
benchmark results. Each record carries a schema version. Decimal values are strings
and timestamps use ISO 8601 UTC. `import_jsonl(content, deduplicate=True)` validates
each record and skips records with IDs already present. Invalid input raises
`ImportRecordError` with the source line number. Export/import does not include
benchmark-run configuration or normalized quality evidence.

## Privacy and payloads

The default `PayloadPolicy.NONE` does not persist raw prompts or responses.
`HASH_ONLY` stores a SHA-256 fingerprint of the request prompt when available, while
still discarding raw payloads. Hashes are not anonymization for predictable inputs.

**Warning:** `PayloadPolicy.FULL` explicitly persists raw prompt and response data.
This can store sensitive user content in the SQLite database, its backups, and JSONL
exports. Enable it only after assessing access controls, retention, export handling,
and backup handling. Do not put secrets or raw prompts in user-controlled metadata;
metadata is stored as supplied.
