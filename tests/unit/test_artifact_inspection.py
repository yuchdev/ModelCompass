from __future__ import annotations

import io
import tarfile
import zipfile
from pathlib import Path

import pytest
from scripts.smoke_install import inspect_sdist, inspect_wheel


@pytest.mark.unit
def test_inspect_sdist_valid_and_prohibited(tmp_path: Path):
    """[Unit] inspect_sdist validation of required and prohibited entries.

    Scenario: Verifies that inspect_sdist accepts well-formed sdists and rejects prohibited files (.env, sqlite, git).
    Boundaries: In-memory/temporary tar archive creation; no external network.
    On failure, first check: member parsing logic or prohibited pattern matching in inspect_sdist.
    """
    valid_sdist = tmp_path / "model_compass-0.1.0.tar.gz"
    with tarfile.open(valid_sdist, "w:gz") as tar:
        for fname in [
            "model_compass-0.1.0/pyproject.toml",
            "model_compass-0.1.0/README.md",
            "model_compass-0.1.0/LICENSE",
            "model_compass-0.1.0/src/model_compass/__init__.py",
            "model_compass-0.1.0/src/model_analytics/__init__.py",
        ]:
            info = tarfile.TarInfo(name=fname)
            info.size = 0
            tar.addfile(info, io.BytesIO())

    # Valid sdist should pass
    inspect_sdist(valid_sdist)

    # Missing required file should fail
    missing_sdist = tmp_path / "missing.tar.gz"
    with tarfile.open(missing_sdist, "w:gz") as tar:
        info = tarfile.TarInfo(name="model_compass-0.1.0/pyproject.toml")
        info.size = 0
        tar.addfile(info, io.BytesIO())
    with pytest.raises(AssertionError, match="missing from sdist"):
        inspect_sdist(missing_sdist)

    # Sdist with .env should fail
    env_sdist = tmp_path / "env.tar.gz"
    with tarfile.open(env_sdist, "w:gz") as tar:
        for fname in [
            "model_compass-0.1.0/pyproject.toml",
            "model_compass-0.1.0/README.md",
            "model_compass-0.1.0/LICENSE",
            "model_compass-0.1.0/src/model_compass/__init__.py",
            "model_compass-0.1.0/src/model_analytics/__init__.py",
            "model_compass-0.1.0/.env",
        ]:
            info = tarfile.TarInfo(name=fname)
            info.size = 0
            tar.addfile(info, io.BytesIO())
    with pytest.raises(AssertionError, match="Prohibited entry"):
        inspect_sdist(env_sdist)

    # Sdist with sqlite database should fail
    db_sdist = tmp_path / "db.tar.gz"
    with tarfile.open(db_sdist, "w:gz") as tar:
        for fname in [
            "model_compass-0.1.0/pyproject.toml",
            "model_compass-0.1.0/README.md",
            "model_compass-0.1.0/LICENSE",
            "model_compass-0.1.0/src/model_compass/__init__.py",
            "model_compass-0.1.0/src/model_analytics/__init__.py",
            "model_compass-0.1.0/data.sqlite3",
        ]:
            info = tarfile.TarInfo(name=fname)
            info.size = 0
            tar.addfile(info, io.BytesIO())
    with pytest.raises(AssertionError, match="Prohibited file type"):
        inspect_sdist(db_sdist)


@pytest.mark.unit
def test_inspect_wheel_valid_and_prohibited(tmp_path: Path):
    """[Unit] inspect_wheel validation of packages, entry points, and prohibited files.

    Scenario: Verifies that inspect_wheel accepts valid wheels and rejects missing packages or entry points.
    Boundaries: Temporary zip archive creation.
    On failure, first check: package/entry-point verification in inspect_wheel.
    """
    valid_wheel = tmp_path / "model_compass-0.1.0-py3-none-any.whl"
    with zipfile.ZipFile(valid_wheel, "w") as zf:
        zf.writestr("model_compass/__init__.py", "")
        zf.writestr("model_analytics/__init__.py", "")
        zf.writestr("model_compass-0.1.0.dist-info/METADATA", "Metadata-Version: 2.1\n")
        zf.writestr(
            "model_compass-0.1.0.dist-info/entry_points.txt",
            "[console_scripts]\nmodel-compass = model_compass.cli:app\nmodel-analytics = model_compass.cli:app\n",
        )

    # Valid wheel passes
    inspect_wheel(valid_wheel)

    # Missing model_analytics should fail
    bad_wheel = tmp_path / "bad.whl"
    with zipfile.ZipFile(bad_wheel, "w") as zf:
        zf.writestr("model_compass/__init__.py", "")
        zf.writestr("model_compass-0.1.0.dist-info/METADATA", "")
        zf.writestr("model_compass-0.1.0.dist-info/entry_points.txt", "")
    with pytest.raises(AssertionError, match="model_analytics"):
        inspect_wheel(bad_wheel)
