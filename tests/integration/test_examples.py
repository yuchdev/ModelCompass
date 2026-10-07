from __future__ import annotations

import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Optional

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[2]
_EXAMPLES_DIR = _REPO_ROOT / "examples"


def _run_example(script_name: str) -> dict[str, object]:
    """Run an example with live LiteLLM execution disabled and parse its JSON output."""
    env = dict(os.environ)
    env["PYTHONPATH"] = str(_REPO_ROOT / "src")
    env.pop("MODEL_COMPASS_EXAMPLE_RUN_LITELLM", None)
    completed = subprocess.run(
        [sys.executable, str(_EXAMPLES_DIR / script_name)],
        cwd=_REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    parsed: object = json.loads(completed.stdout)
    assert isinstance(parsed, dict)
    return {str(key): value for key, value in parsed.items()}


def _list_length(data: dict[str, object], key: str) -> Optional[int]:
    """Return the length of a JSON list field, or None if the field is not a list."""
    value = data.get(key)
    return len(value) if isinstance(value, list) else None


def _string_set(data: dict[str, object], key: str) -> Optional[set[str]]:
    """Return a JSON list field as a string set, or None if it contains non-strings."""
    value = data.get(key)
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return {item for item in value if isinstance(item, str)}


Expectation = Callable[[dict[str, object]], bool]
_EXAMPLES: tuple[tuple[str, Expectation], ...] = (
    ("list_models.py", lambda data: _list_length(data, "models") == 2),
    ("estimate_cost.py", lambda data: data["complete"] is True and data["total"] != "0"),
    (
        "compare_models.py",
        lambda data: data["selected_policy"] == "best" and _list_length(data, "candidates") == 2,
    ),
    ("constrained_selection.py", lambda data: data["selected"] == "demo:small"),
    (
        "pareto_frontier.py",
        lambda data: _string_set(data, "frontier") == {"demo:small", "demo:large"},
    ),
    ("benchmark_fake_backend.py", lambda data: data["results"] == 1 and data["score"] == "1"),
    (
        "execute_with_litellm.py",
        lambda data: data["mode"] == "dry-run" and data["model_id"] == "openai/gpt-4o-mini",
    ),
)


@pytest.mark.integration
@pytest.mark.parametrize(
    ("script_name", "expectation"),
    _EXAMPLES,
)
def test_examples_run_offline(script_name: str, expectation: Expectation):
    """[Integration] example scripts: the shipped examples execute without network access by default.

    Scenario: Run each documented example script from the examples/ directory and inspect its JSON output.
    Boundaries: Subprocess execution only; no live provider access is required.
    On failure, first check: the script's imports and whether it still defaults to offline behavior.
    """
    data = _run_example(script_name)
    assert expectation(data)
