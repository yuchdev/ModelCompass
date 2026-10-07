from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / "examples"


def _run_example(script_name: str) -> dict[str, object]:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    completed = subprocess.run(
        [sys.executable, str(_EXAMPLES_DIR / script_name)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    return json.loads(completed.stdout)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("script_name", "expectation"),
    [
        ("list_models.py", lambda data: len(data["models"]) == 2),
        ("estimate_cost.py", lambda data: data["complete"] is True and data["total"] != "0"),
        ("compare_models.py", lambda data: data["selected_policy"] == "best" and len(data["candidates"]) == 2),
        ("constrained_selection.py", lambda data: data["selected"] == "demo:small"),
        ("pareto_frontier.py", lambda data: set(data["frontier"]) == {"demo:small", "demo:large"}),
        ("benchmark_fake_backend.py", lambda data: data["results"] == 1 and data["score"] == "1"),
        (
            "execute_with_litellm.py",
            lambda data: data["mode"] == "dry-run" and data["model_id"] == "openai/gpt-4o-mini",
        ),
    ],
)
def test_examples_run_offline(script_name: str, expectation):
    """[Unit] example scripts: the shipped examples execute without network access by default.

    Scenario: Run each documented example script from the examples/ directory and inspect its JSON output.
    Boundaries: Subprocess execution only; no live provider access is required.
    On failure, first check: the script's imports and whether it still defaults to offline behavior.
    """
    data = _run_example(script_name)
    assert expectation(data)
