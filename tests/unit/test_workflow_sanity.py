from __future__ import annotations

from pathlib import Path

import pytest
import yaml


@pytest.mark.unit
def test_ci_workflow_sanity():
    """[Unit] CI workflow structure and job verification.

    Scenario: Verifies that ci.yml defines all 8 required jobs, python matrix, and coverage gate.
    Boundaries: Local YAML file parsing; no GitHub API interaction.
    On failure, first check: missing jobs, incorrect job names, or syntax errors in ci.yml.
    """
    repo_root = Path(__file__).resolve().parents[2]
    ci_path = repo_root / ".github" / "workflows" / "ci.yml"
    assert ci_path.exists(), "ci.yml must exist"

    with ci_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    jobs = data.get("jobs", {})
    required_jobs = [
        "ruff-format",
        "ruff-lint",
        "mypy",
        "test-matrix",
        "coverage-gate",
        "docs-build",
        "package-build",
        "smoke-install",
    ]
    for job_id in required_jobs:
        assert job_id in jobs, f"Job '{job_id}' missing from ci.yml"

    # Verify python matrix in test-matrix
    matrix = jobs["test-matrix"].get("strategy", {}).get("matrix", {})
    py_versions = matrix.get("python-version", [])
    assert "3.11" in py_versions
    assert "3.12" in py_versions
    assert "3.13" in py_versions

    # Verify coverage gate
    cov_steps = jobs["coverage-gate"].get("steps", [])
    cov_runs = [s.get("run", "") for s in cov_steps if "run" in s]
    assert any("--cov-fail-under=90" in r for r in cov_runs)

    # Verify package-build and smoke-install use release-saga
    pkg_steps = jobs["package-build"].get("steps", [])
    pkg_runs = [s.get("run", "") for s in pkg_steps if "run" in s]
    assert any("release-saga" in r for r in pkg_runs)

    smoke_steps = jobs["smoke-install"].get("steps", [])
    smoke_runs = [s.get("run", "") for s in smoke_steps if "run" in s]
    assert any("release-saga" in r for r in smoke_runs)


@pytest.mark.unit
def test_live_workflow_sanity():
    """[Unit] Live smoke workflow dispatch and guard verification.

    Scenario: Verifies that live.yml triggers only via workflow_dispatch with explicit model and budget inputs.
    Boundaries: Local YAML file parsing; no GitHub API interaction.
    On failure, first check: trigger misconfiguration or missing security budget guard in live.yml.
    """
    repo_root = Path(__file__).resolve().parents[2]
    live_path = repo_root / ".github" / "workflows" / "live.yml"
    assert live_path.exists(), "live.yml must exist"

    with live_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    triggers = data.get("on") or data.get(True) or {}
    assert "workflow_dispatch" in triggers
    assert "pull_request" not in triggers, "Live workflow must not trigger automatically on pull requests"
    assert "push" not in triggers, "Live workflow must not trigger on push"

    inputs = triggers["workflow_dispatch"].get("inputs", {})
    assert "model" in inputs
    assert "max_cost_usd" in inputs

    steps = data.get("jobs", {}).get("live-smoke", {}).get("steps", [])
    runs = [s.get("run", "") for s in steps if "run" in s]
    assert any("max_cost_usd" in r for r in runs), "Budget validation step missing"


@pytest.mark.unit
def test_release_workflow_sanity():
    """[Unit] Release workflow protection and Trusted Publishing verification.

    Scenario: Verifies that release.yml cannot publish on normal branch pushes and configures OIDC publishing.
    Boundaries: Local YAML file parsing; no GitHub API interaction.
    On failure, first check: release triggers or publishing permissions in release.yml.
    """
    repo_root = Path(__file__).resolve().parents[2]
    rel_path = repo_root / ".github" / "workflows" / "release.yml"
    assert rel_path.exists(), "release.yml must exist"

    with rel_path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)

    triggers = data.get("on") or data.get(True) or {}
    if "push" in triggers:
        assert "branches" not in triggers["push"], "Release workflow must not trigger on branch push"
        assert "tags" in triggers["push"], "Push trigger must only be for tags"

    jobs = data.get("jobs", {})
    pub_job = jobs.get("publish-pypi", {})
    perms = pub_job.get("permissions", {})
    assert perms.get("id-token") == "write", "Publish job must have id-token: write for Trusted Publishing"
