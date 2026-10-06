"""Package import and public API smoke tests."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

import model_compass
from model_compass import (
    BenchmarkError,
    ConfigurationError,
    DependencyError,
    ModelCompassError,
    PricingError,
    SelectionError,
    StorageError,
    __version__,
    application,
)
from model_compass.cli.app import app
from model_compass.config import AppPaths, default_paths

runner = CliRunner()


@pytest.mark.unit
def test_import():
    """[Unit] package import: verifies model_compass imports without error.

    Scenario: Reference the already-imported model_compass module.
    Boundaries: Pure import check; no I/O.
    On failure, first check: model_compass/__init__.py for a raised exception at import time.
    """
    assert model_compass is not None


@pytest.mark.unit
def test_version_is_string():
    """[Unit] version string: verifies __version__ is a non-empty string.

    Scenario: Check the type and truthiness of model_compass.__version__.
    Boundaries: Pure attribute check; no I/O.
    On failure, first check: how __version__ is set in model_compass/__init__.py.
    """
    assert isinstance(__version__, str)
    assert __version__


@pytest.mark.unit
def test_exception_hierarchy():
    """[Unit] exception hierarchy: verifies public exceptions derive from ModelCompassError.

    Scenario: Check issubclass() for each public exception against ModelCompassError and Exception.
    Boundaries: Pure class-hierarchy check; no I/O.
    On failure, first check: each exception class's base in model_compass/exceptions.py.
    """
    assert issubclass(ConfigurationError, ModelCompassError)
    assert issubclass(DependencyError, ModelCompassError)
    assert issubclass(BenchmarkError, ModelCompassError)
    assert issubclass(PricingError, ModelCompassError)
    assert issubclass(SelectionError, ModelCompassError)
    assert issubclass(StorageError, ModelCompassError)
    assert issubclass(ModelCompassError, Exception)


@pytest.mark.unit
def test_cli_help():
    """[E2E] CLI help: verifies `--help` exits 0 and mentions the command name or usage.

    Scenario: Invoke the Typer app with ["--help"] through CliRunner.
    Boundaries: The whole CLI entry point runs in-process; no network or filesystem writes.
    On failure, first check: the Typer app's name/help text in cli/app.py.
    """
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "model-compass" in result.output.lower() or "usage" in result.output.lower()


@pytest.mark.unit
def test_cli_version():
    """[E2E] CLI version: verifies the `version` command prints the version string.

    Scenario: Invoke the Typer app with ["version"] through CliRunner.
    Boundaries: The whole CLI entry point runs in-process; no network or filesystem writes.
    On failure, first check: the `version` command in cli/app.py.
    """
    result = runner.invoke(app, ["version"])
    assert result.exit_code == 0
    assert __version__ in result.output


@pytest.mark.unit
def test_cli_doctor_table():
    """[E2E] doctor table output: verifies the default `doctor` output exits 0 and reports itself.

    Scenario: Invoke the Typer app with ["doctor"] through CliRunner.
    Boundaries: The whole CLI entry point runs in-process; no network or filesystem writes.
    On failure, first check: the `doctor` command's table rendering in cli/app.py.
    """
    result = runner.invoke(app, ["doctor"])
    assert result.exit_code == 0
    assert "doctor" in result.output.lower()


@pytest.mark.unit
def test_cli_doctor_json():
    """[E2E] doctor JSON output: verifies `doctor --format json` emits valid JSON with required keys.

    Scenario: Invoke the Typer app with ["doctor", "--format", "json"] through CliRunner.
    Boundaries: The whole CLI entry point runs in-process; no network or filesystem writes.
    On failure, first check: the `doctor` command's JSON payload construction in cli/app.py.
    """
    result = runner.invoke(app, ["doctor", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert "schema_version" in data
    assert "package_version" in data
    assert "python_version" in data
    assert "platform" in data
    assert "litellm_available" in data
    assert "paths" in data
    paths_data = data["paths"]
    assert "config_dir" in paths_data
    assert "data_dir" in paths_data
    assert "cache_dir" in paths_data


@pytest.mark.unit
def test_cli_doctor_reports_litellm_failure(monkeypatch: pytest.MonkeyPatch):
    """[Local] doctor LiteLLM failure: verifies doctor reports an unavailable LiteLLM instead of crashing.

    Scenario: Set sys.modules["litellm"] = None, the documented way to force
        ModuleNotFoundError on import, then invoke `doctor` in both JSON and table modes.
    Boundaries: Only sys.modules is faked; the CLI entry point and its import handling run for real.
    On failure, first check: the `doctor` command's ImportError handling in cli/app.py.
    """
    monkeypatch.setitem(sys.modules, "litellm", None)

    json_result = runner.invoke(app, ["doctor", "--format", "json"])
    table_result = runner.invoke(app, ["doctor"])

    assert json_result.exit_code == 0
    data = json.loads(json_result.output)
    assert data["litellm_available"] is False
    assert data["litellm_error"]
    assert table_result.exit_code == 0


@pytest.mark.unit
def test_doctor_json_no_secrets():
    """[E2E] doctor secret redaction: verifies doctor JSON never echoes known secret env values.

    Scenario: For each known secret env var present in the environment, invoke `doctor
        --format json` and check its value doesn't appear in the output.
    Boundaries: The whole CLI entry point runs in-process; reads real process environment.
    On failure, first check: whether the `doctor` command's JSON payload includes raw env values.
    """
    secret_vars = ["OPENROUTER_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY"]
    for var in secret_vars:
        secret_value = os.environ.get(var, "")
        if not secret_value:
            continue
        result = runner.invoke(app, ["doctor", "--format", "json"])
        assert secret_value not in result.output, f"Secret {var} found in doctor output"


@pytest.mark.unit
def test_import_does_not_create_dirs(tmp_path: Path):
    """[Integration] import side effects: verifies importing model_compass creates no user directories.

    Scenario: Run `import model_compass; default_paths()` in a subprocess with XDG env
        vars pointed at a temp directory, then check none of its subdirectories exist.
    Boundaries: A real Python subprocess and filesystem are used; no network.
    On failure, first check: config.default_paths() for eager directory creation.
    """
    env = dict(os.environ)
    env["XDG_CONFIG_HOME"] = str(tmp_path / "config")
    env["XDG_DATA_HOME"] = str(tmp_path / "data")
    env["XDG_CACHE_HOME"] = str(tmp_path / "cache")
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[2] / "src")

    code = "import model_compass, model_compass.config as c; c.default_paths()"
    completed = subprocess.run(
        [sys.executable, "-c", code],
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert not (tmp_path / "config").exists()
    assert not (tmp_path / "data").exists()
    assert not (tmp_path / "cache").exists()


@pytest.mark.unit
def test_application_module_imports():
    """[Unit] application facade import: verifies the module imports without side effects.

    Scenario: Reference the already-imported model_compass.application module.
    Boundaries: Pure import check; no I/O.
    On failure, first check: model_compass/application.py for a raised exception at import time.
    """
    assert application is not None


@pytest.mark.unit
def test_default_paths_returns_app_paths():
    """[Unit] default paths shape: verifies default_paths() returns an AppPaths of Path attributes.

    Scenario: Call default_paths() and check the type of its result and each directory attribute.
    Boundaries: Pure function call; no filesystem writes.
    On failure, first check: config.default_paths()'s return type construction.
    """
    paths = default_paths()
    assert isinstance(paths, AppPaths)
    assert isinstance(paths.config_dir, Path)
    assert isinstance(paths.data_dir, Path)
    assert isinstance(paths.cache_dir, Path)
