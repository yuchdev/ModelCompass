# Configuration

Model Compass keeps configuration intentionally small. There is no file-backed application config schema yet; the CLI accepts `--config` as a recorded path for future use, but the current release does not load settings from that file.

## Precedence

### Paths

```text
CLI path flags
  -> platform defaults from platformdirs
  -> write-only creation of directories when a store or cache actually needs them
```

- `--data-dir` overrides the default application data directory.
- `--cache-dir` overrides the catalog cache directory.
- `--db` overrides the SQLite observation database path.
- Importing the package does not create directories.

### Provider credentials

Provider credentials are read from environment variables only.

- `OPENROUTER_API_KEY`
- `OPENAI_API_KEY`
- `ANTHROPIC_API_KEY`

The CLI reports which of those names are present, but never their values. Nothing in the library persists secrets automatically.

## Defaults

Default path values come from `platformdirs` via `model_compass.config.default_paths()`. The returned paths are platform-correct, but they remain inert until something writes to them.
