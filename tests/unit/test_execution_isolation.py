from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src" / "model_compass"
_LITELLM_IMPORT = re.compile(r"""^\s*(?:import|from)\s+litellm\b|import_module\(\s*["']litellm""", re.MULTILINE)
_ALLOWED = {
    "catalogs/litellm.py",
    "execution/backend.py",
    "metrics/tokens.py",
    "cli/app.py",
}


@pytest.mark.unit
def test_litellm_is_only_imported_by_adapter_modules():
    """[Unit] import isolation: only execution/catalog/token adapters (and the doctor check) touch LiteLLM.

    Scenario: Scan every module under src/model_compass for a LiteLLM import.
    Boundaries: Reads source files only; no imports are executed.
    On failure, first check: the offending module; move LiteLLM use behind ExecutionBackend or a catalog adapter.
    """
    offenders = sorted(
        str(path.relative_to(SRC))
        for path in SRC.rglob("*.py")
        if _LITELLM_IMPORT.search(path.read_text(encoding="utf-8")) and str(path.relative_to(SRC)) not in _ALLOWED
    )
    assert offenders == []


@pytest.mark.unit
def test_selection_and_domain_do_not_depend_on_execution():
    """[Unit] layering: selection, domain, and storage never import the execution package.

    Scenario: Scan those packages' sources for imports of model_compass.execution.
    Boundaries: Reads source files only; no imports are executed.
    On failure, first check: the offending import; selection must stay independent of LiteLLM and execution.
    """
    pattern = re.compile(r"^\s*(?:from|import)\s+model_compass\.execution", re.MULTILINE)
    offenders = [
        str(path.relative_to(SRC))
        for package in ("selection", "domain", "storage")
        for path in (SRC / package).rglob("*.py")
        if pattern.search(path.read_text(encoding="utf-8"))
    ]
    assert offenders == []


@pytest.mark.unit
def test_importing_the_package_does_not_import_litellm():
    """[Unit] lazy import: importing model_compass.execution does not import LiteLLM.

    Scenario: Import the execution package in a fresh interpreter and inspect sys.modules.
    Boundaries: Spawns a Python subprocess; no network.
    On failure, first check: top-level imports in execution/backend.py; use importlib at call time.
    """
    code = "import sys, model_compass, model_compass.execution; print('litellm' in sys.modules)"
    output = subprocess.run([sys.executable, "-c", code], check=True, capture_output=True, text=True).stdout
    assert output.strip() == "False"
