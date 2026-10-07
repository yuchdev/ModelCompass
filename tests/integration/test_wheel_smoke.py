from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
from scripts.smoke_install import inspect_sdist, inspect_wheel, smoke_install

_REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.integration
def test_wheel_build_inspect_and_smoke_install(tmp_path: Path):
    """[Integration] Wheel build, artifact inspection, and clean environment smoke installation.

    Scenario: Builds sdist and wheel using uv build, verifies artifact contents, and performs smoke installation and CLI runs in an isolated virtual environment.
    Boundaries: Local filesystem and subprocess; executes isolated uv venv without external network.
    On failure, first check: package packaging configuration, missing build dependencies, or entry points.
    """
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()

    # 1. Build sdist and wheel
    build_cmd = ["uv", "build", "--out-dir", str(dist_dir)]
    res = subprocess.run(build_cmd, cwd=str(_REPO_ROOT), capture_output=True, text=True, check=False)
    assert res.returncode == 0, f"uv build failed: {res.stderr}\n{res.stdout}"

    wheels = list(dist_dir.glob("*.whl"))
    sdists = list(dist_dir.glob("*.tar.gz"))

    assert len(wheels) == 1, f"Expected 1 wheel, found {len(wheels)}"
    assert len(sdists) == 1, f"Expected 1 sdist, found {len(sdists)}"

    wheel_path = wheels[0]
    sdist_path = sdists[0]

    # 2. Inspect sdist (must contain required metadata, no .env, no cache, no sqlite, no git)
    inspect_sdist(sdist_path)

    # 3. Inspect wheel (must contain model_compass, model_analytics, entry points)
    inspect_wheel(wheel_path)

    # 4. Smoke install in clean environment and run CLI & import checks
    smoke_install(wheel_path)
