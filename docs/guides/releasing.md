# Releasing Model Compass

This guide outlines the release process, package validation, PyPI/TestPyPI Trusted Publishing setup, and rollback/yank guidance for Model Compass.

## Versioning Strategy

Model Compass follows [Semantic Versioning 2.0.0](https://semver.org/).
For early development (0.y.z):
- Initial public release is `0.1.0`.
- Minor releases (`0.x.0`) may introduce new features or breaking changes while in alpha/beta.
- Patch releases (`0.1.x`) contain bugfixes and backward-compatible improvements.

The version is defined statically in `pyproject.toml` and retrieved at runtime via `importlib.metadata`:

```python
import model_compass

print(model_compass.__version__)
```

The compatibility alias `model_analytics` also exposes the identical `__version__`:

```python
import model_analytics

print(model_analytics.__version__)
```

## Release Artifacts

Release builds produce two standardized distribution formats:
1. **Source distribution (`sdist`)**: `.tar.gz` containing source code, license, documentation, and build metadata.
2. **Built distribution (`wheel`)**: `.whl` containing packaged modules (`model_compass` and `model_analytics`) and entry point scripts (`model-compass` and `model-analytics`).

Artifacts are built reproducibly using `uv build` or `release-saga`.

### Artifact Cleanliness Invariants

Release artifacts MUST NOT contain:
- Development configuration (`.env`, `.venv`)
- Local databases (`*.sqlite`, `*.db`)
- Cache directories (`__pycache__`, `.pytest_cache`, `.mypy_cache`, `.ruff_cache`)
- Secrets or credentials
- Version control metadata (`.git`)

## Trusted Publishing Setup

Model Compass uses [PyPI Trusted Publishing](https://docs.pypi.org/trusted-publishers/) via OpenID Connect (OIDC) tokens instead of long-lived API tokens.

### 1. PyPI Configuration

1. Log in to [PyPI](https://pypi.org/) (or [TestPyPI](https://test.pypi.org/)).
2. Navigate to **Publishing** in account or project settings.
3. Add a new GitHub publisher:
   - **Owner**: `yuchdev`
   - **Repository name**: `ModelCompass`
   - **Workflow name**: `release.yml`
   - **Environment name**: `pypi` (or `testpypi`)

### 2. GitHub Environments

In the GitHub repository settings:
1. Go to **Settings** > **Environments**.
2. Create environment `pypi` (requires deployment protection rules if desired).
3. Create environment `testpypi` for staging verification.

GitHub Actions uses `pypa/gh-action-pypi-publish` with `id-token: write` permissions to obtain short-lived OIDC exchange tokens.

## Step-by-Step Release Workflow

### Step 1: Quality Validation

Ensure all quality gates pass locally before initiating a release:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src tests
uv run pytest -m "not live" --cov=model_compass --cov-branch --cov-fail-under=90
uv run mkdocs build --strict
uv build --out-dir .dist
```

### Step 2: Prepare Release Notes

Update `RELEASE_NOTES.json` with the new version, title, release date, and changelog highlights:

```json
{
  "releases": [
    {
      "version": "0.1.0",
      "date": "2026-10-07",
      "title": "Model Compass 0.1.0",
      "notes": [
        "Initial release: request-aware model analytics, comparison, and selection.",
        "CLI tools: model-compass and model-analytics entry points."
      ]
    }
  ]
}
```

Update `version = "0.1.0"` in `pyproject.toml` if incrementing.

### Step 3: Tag and Trigger

Releases are triggered exclusively via git tags or manual `workflow_dispatch`. Normal branch pushes (e.g. `main` or PRs) **cannot** publish to PyPI.

To release:
```bash
git tag -a v0.1.0 -m "Release v0.1.0"
git push origin v0.1.0
```

The `.github/workflows/release.yml` workflow will:
1. Validate package metadata and release notes.
2. Build sdist and wheel artifacts using `uv build` and `release-saga`.
3. Smoke-test the built wheel in an isolated virtual environment.
4. Publish artifacts to PyPI (or TestPyPI) via OIDC Trusted Publishing.
5. Create a GitHub Release referencing the tag and notes.

## Post-Release Verification

Verify the published package in a clean environment:

```bash
uv venv /tmp/smoke-env
source /tmp/smoke-env/bin/activate
uv pip install model-compass

# Smoke checks
python -c "import model_compass; print(model_compass.__version__)"
python -c "import model_analytics; print(model_analytics.__version__)"
model-compass --help
model-analytics version
```

## Rollback and Yank Guidance

PyPI does **not** allow re-uploading an existing version, nor deleting a version to re-upload modified artifacts with the same version number. Once published, a version is immutable.

### When a Release Contains a Critical Bug

1. **Yank the Release on PyPI**:
   - Log into PyPI, navigate to project management > **Releases**.
   - Select **Options** > **Yank version**.
   - Provide a clear reason (e.g., `Critical regression in catalog ingestion; see issue #42`).
   - Yanking prevents `pip install model-compass` from picking the bad release by default, while avoiding breaking builds that pinned exact versions (`model-compass==0.1.0`).

2. **Publish a Patch Release**:
   - Fix the defect on a release branch or `main`.
   - Bump version to `0.1.1` in `pyproject.toml`.
   - Update `RELEASE_NOTES.json`.
   - Tag `v0.1.1` and let the release workflow publish the fix.

3. **Never Delete Releases**:
   - Deleting releases on PyPI causes hard dependency breakage for any consumer with pinned lockfiles. Always prefer yanking followed by an immediate patch release.
