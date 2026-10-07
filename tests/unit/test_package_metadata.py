from __future__ import annotations

import json
import tomllib
from importlib import metadata
from pathlib import Path

import pytest

import model_analytics
import model_compass


@pytest.mark.unit
def test_pyproject_metadata_fields():
    """[Unit] pyproject.toml package metadata completeness.

    Scenario: Verifies that pyproject.toml contains all required distribution metadata fields.
    Boundaries: Local pyproject.toml filesystem parse; no external calls.
    On failure, first check: missing, misnamed, or improperly typed fields in pyproject.toml.
    """
    repo_root = Path(__file__).resolve().parents[2]
    pyproject_path = repo_root / "pyproject.toml"
    assert pyproject_path.exists(), "pyproject.toml must exist"

    with pyproject_path.open("rb") as f:
        data = tomllib.load(f)

    project = data.get("project", {})
    assert project.get("name") == "model-compass"
    assert project.get("version") == "0.1.0"
    assert project.get("description")
    assert project.get("readme") == "README.md"
    assert project.get("license") == {"file": "LICENSE"}
    assert project.get("requires-python") == ">=3.11"

    dependencies = project.get("dependencies", [])
    assert len(dependencies) > 0

    classifiers = project.get("classifiers", [])
    assert any("Python :: 3.11" in c for c in classifiers)
    assert any("Python :: 3.12" in c for c in classifiers)
    assert any("Python :: 3.13" in c for c in classifiers)
    assert not any(c.startswith("License ::") for c in classifiers), (
        "License classifier must not be specified when license file is provided (PEP 639)"
    )

    keywords = project.get("keywords", [])
    assert len(keywords) >= 3
    assert "model-selection" in keywords

    urls = project.get("urls", {})
    assert urls.get("Repository") == "https://github.com/yuchdev/ModelCompass"
    assert urls.get("Documentation") == "https://yuchdev.github.io/ModelCompass"
    assert urls.get("Issues") == "https://github.com/yuchdev/ModelCompass/issues"

    scripts = project.get("scripts", {})
    assert scripts.get("model-compass") == "model_compass.cli:app"
    assert scripts.get("model-analytics") == "model_compass.cli:app"

    build_system = data.get("build-system", {})
    assert build_system.get("build-backend") == "uv_build"

    uv_build = data.get("tool", {}).get("uv", {}).get("build-backend", {})
    module_names = uv_build.get("module-name", [])
    assert "model_compass" in module_names
    assert "model_analytics" in module_names


@pytest.mark.unit
def test_version_alignment_with_distribution_metadata():
    """[Unit] package version alignment with distribution metadata.

    Scenario: Verifies that model_compass and model_analytics export matching versions that align with distribution metadata.
    Boundaries: In-process importlib metadata and module inspection.
    On failure, first check: version constant drift between pyproject.toml and package __init__.py files.
    """
    assert model_compass.__version__ == "0.1.0"
    assert model_analytics.__version__ == "0.1.0"
    assert model_compass.__version__ == model_analytics.__version__

    dist_version = metadata.version("model-compass")
    assert model_compass.__version__ == dist_version
    assert model_analytics.__version__ == dist_version


@pytest.mark.unit
def test_release_notes_json_validity():
    """[Unit] RELEASE_NOTES.json schema and entry validation.

    Scenario: Verifies that RELEASE_NOTES.json is valid JSON with release entries corresponding to v0.1.0.
    Boundaries: Local RELEASE_NOTES.json filesystem parse.
    On failure, first check: JSON syntax errors or missing required keys in RELEASE_NOTES.json.
    """
    repo_root = Path(__file__).resolve().parents[2]
    notes_path = repo_root / "RELEASE_NOTES.json"
    assert notes_path.exists(), "RELEASE_NOTES.json must exist"

    with notes_path.open("r", encoding="utf-8") as f:
        data = json.load(f)

    assert "releases" in data
    assert isinstance(data["releases"], dict)
    assert "0.1.0" in data["releases"]

    entry = data["releases"]["0.1.0"]
    notes = entry.get("release_notes", [])
    assert isinstance(notes, list)
    assert len(notes) >= 1
