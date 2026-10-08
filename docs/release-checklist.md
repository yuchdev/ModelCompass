# v0.1 release-candidate checklist

This is a **gate**, not evidence that a release is approved. Mark an item complete only after a linked log, artifact, or manual confirmation exists. Issue [#12](https://github.com/yuchdev/ModelCompass/issues/12) tracks this audit.

## Automated gates

- [ ] From a clean checkout: `uv sync --all-groups`
- [ ] `uv run ruff format --check .`
- [ ] `uv run ruff check .`
- [ ] `uv run mypy src tests`
- [ ] `uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90`
- [ ] Manually review uncovered branches in pricing, constraints, selection, Pareto, serialization, and storage migrations.
- [ ] `uv run mkdocs build --strict`
- [ ] `uv build`
- [ ] Inspect wheel and source distribution for sensitive/development files.

## Independent installation smoke

- [ ] Install wheel in a fresh environment outside the repository.
- [ ] Import both `model_compass` and compatibility alias `model_analytics`.
- [ ] Run `model-compass --help` and `model-analytics --help`.
- [ ] Check package metadata and import all packaged modules with repository absent from `PYTHONPATH`.
- [ ] Exercise an offline selection/estimation against a bundled or user-provided fixture.

## Compatibility, security, and performance

- [ ] Validate malformed/unsupported OpenRouter schema, offline network failure, stale/corrupt cache, and invalid config.
- [ ] Validate no-eligible-candidate and missing quality/price behaviors.
- [ ] Validate LiteLLM authentication, rate-limit, context and provider failure classification.
- [ ] Validate locked/corrupt SQLite error paths where safe.
- [ ] Check credentials never appear in logs/exceptions.
- [ ] Audit provider imports, storage protocols, import-time side effects, API exports, Decimal JSON encoding and deterministic output.
- [ ] Check mutation boundaries (override threshold; rank direction; missing vs zero; constraints before ranking; observed vs estimated; failure counts; stale-flag polarity).
- [ ] Record local benchmark results for snapshot parsing, hundreds-of-model comparison, Pareto, and thousands-of-rows SQLite aggregation. Do not enforce CI timing thresholds.
- [ ] Optional, explicitly authorized: opt-in live OpenRouter catalog and low-cost execution smoke; store only sanitized/minimized fixtures.

## Publication (manual)

- [ ] Version in `pyproject.toml` and `__version__` confirmed.
- [ ] Name `model-compass` and both CLI entry points verified.
- [ ] `CHANGELOG.md` updated and release notes checked.
- [ ] PyPI/TestPyPI Trusted Publisher configured and verified.
- [ ] GitHub `pypi`/`testpypi` environments protected appropriately.
- [ ] Approve release candidate after reviewing all evidence.
- [ ] Create and push release tag; verify GitHub Release.
- [ ] Post-publish fresh install and CLI/import smoke.

**Publishing is deliberately excluded from issue #12 unless expressly authorized.**

## Evidence log

| Gate | Evidence URL or command output | Status |
| --- | --- | --- |
| Static checks | Not yet recorded | Unverified |
| Tests / branch coverage | Not yet recorded | Unverified |
| Strict docs | Not yet recorded | Unverified |
| Wheel smoke | Not yet recorded | Unverified |
| Live compatibility | Credentials/authorization not supplied | Not run |
| Performance | Not yet recorded | Unverified |
| Registry / environment protections | Requires owner verification | Unverified |
