#!/usr/bin/env python3
"""Smoke install and artifact validation script for Model Compass.

This script validates that built distribution artifacts (wheel and sdist)
meet all packaging hygiene standards and that the wheel can be cleanly installed
and executed in an isolated environment without relying on the repository source tree.
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path
from typing import Optional

PROHIBITED_EXTENSIONS = {".sqlite", ".sqlite3", ".db", ".pyc"}
PROHIBITED_NAMES = {".env", ".git", ".venv", "venv", "__pycache__"}


def inspect_sdist(sdist_path: Path):
    """Validate that the source distribution contains required files and no secrets or junk."""
    print(f"Inspecting sdist: {sdist_path.name}")
    if not sdist_path.is_file():
        raise FileNotFoundError(f"sdist not found: {sdist_path}")

    with tarfile.open(sdist_path, "r:gz") as tar:
        names = [m.name for m in tar.getmembers()]

    # Normalize member names by stripping the top-level directory (e.g. model_compass-0.1.0/)
    relative_names = []
    for name in names:
        parts = Path(name).parts
        rel = "/".join(parts[1:]) if len(parts) > 1 else ""
        if rel:
            relative_names.append(rel)

    required_substrings = [
        "pyproject.toml",
        "README.md",
        "LICENSE",
        "src/model_compass/__init__.py",
        "src/model_analytics/__init__.py",
    ]
    for req in required_substrings:
        if not any(req in rel for rel in relative_names):
            raise AssertionError(f"Required file '{req}' missing from sdist {sdist_path.name}")

    # Check prohibited contents
    for rel in relative_names:
        p = Path(rel)
        if any(part in PROHIBITED_NAMES for part in p.parts):
            raise AssertionError(f"Prohibited entry '{rel}' found in sdist {sdist_path.name}")
        if p.suffix in PROHIBITED_EXTENSIONS:
            raise AssertionError(f"Prohibited file type '{rel}' found in sdist {sdist_path.name}")
        if any(secret in rel.lower() for secret in ["id_rsa", ".pem", ".key", "secret"]):
            raise AssertionError(f"Suspicious potential secret '{rel}' found in sdist")

    print(f"  sdist {sdist_path.name} passed inspection ({len(names)} entries).")


def inspect_wheel(wheel_path: Path):
    """Validate that the wheel contains required packages and entry points and no junk."""
    print(f"Inspecting wheel: {wheel_path.name}")
    if not wheel_path.is_file():
        raise FileNotFoundError(f"wheel not found: {wheel_path}")

    with zipfile.ZipFile(wheel_path, "r") as zf:
        names = zf.namelist()
        entry_points_text = ""
        for name in names:
            if name.endswith("entry_points.txt"):
                entry_points_text = zf.read(name).decode("utf-8")

    # Check packages
    has_model_compass = any(n.startswith("model_compass/") for n in names)
    has_model_analytics = any(n.startswith("model_analytics/") for n in names)
    if not has_model_compass:
        raise AssertionError(f"'model_compass' package missing from wheel {wheel_path.name}")
    if not has_model_analytics:
        raise AssertionError(f"'model_analytics' package missing from wheel {wheel_path.name}")

    # Check entry points
    if "model-compass" not in entry_points_text or "model-analytics" not in entry_points_text:
        raise AssertionError(f"Entry points 'model-compass' and 'model-analytics' missing from wheel {wheel_path.name}")

    # Check prohibited contents
    for name in names:
        p = Path(name)
        if any(part in PROHIBITED_NAMES for part in p.parts):
            raise AssertionError(f"Prohibited entry '{name}' found in wheel {wheel_path.name}")
        if p.suffix in PROHIBITED_EXTENSIONS:
            raise AssertionError(f"Prohibited file type '{name}' found in wheel {wheel_path.name}")
        if any(secret in name.lower() for secret in ["id_rsa", ".pem", ".key", "secret"]):
            raise AssertionError(f"Suspicious potential secret '{name}' found in wheel")

    print(f"  wheel {wheel_path.name} passed inspection ({len(names)} entries).")


def smoke_install(wheel_path: Path, python_exe: Optional[str] = None):
    """Install the wheel in an isolated environment and run smoke verification commands."""
    print(f"Testing smoke install of {wheel_path.name}...")
    base_python = python_exe or sys.executable

    with tempfile.TemporaryDirectory(prefix="mc-smoke-") as tmp_dir:
        tmp_path = Path(tmp_dir)
        venv_path = tmp_path / "venv"
        work_dir = tmp_path / "work"
        work_dir.mkdir()

        # Create venv using uv or python venv
        uv_cmd = shutil_which("uv")
        if uv_cmd:
            subprocess.run([uv_cmd, "venv", str(venv_path), "--python", base_python], check=True)
            if os.name == "nt":
                venv_python = venv_path / "Scripts" / "python.exe"
                venv_compass = venv_path / "Scripts" / "model-compass.exe"
                venv_analytics = venv_path / "Scripts" / "model-analytics.exe"
            else:
                venv_python = venv_path / "bin" / "python"
                venv_compass = venv_path / "bin" / "model-compass"
                venv_analytics = venv_path / "bin" / "model-analytics"
            # Install wheel
            subprocess.run([uv_cmd, "pip", "install", str(wheel_path), "--python", str(venv_python)], check=True)
        else:
            subprocess.run([base_python, "-m", "venv", str(venv_path)], check=True)
            if os.name == "nt":
                venv_python = venv_path / "Scripts" / "python.exe"
                venv_pip = venv_path / "Scripts" / "pip.exe"
                venv_compass = venv_path / "Scripts" / "model-compass.exe"
                venv_analytics = venv_path / "Scripts" / "model-analytics.exe"
            else:
                venv_python = venv_path / "bin" / "python"
                venv_pip = venv_path / "bin" / "pip"
                venv_compass = venv_path / "bin" / "model-compass"
                venv_analytics = venv_path / "bin" / "model-analytics"
            subprocess.run([str(venv_pip), "install", str(wheel_path)], check=True)

        # 1. Smoke check: import model_analytics, import model_compass, check version matches distribution metadata
        print("  Checking imports and version in clean environment...")
        verify_code = (
            "import model_compass; "
            "import model_analytics; "
            "from importlib.metadata import version; "
            "dist_ver = version('model-compass'); "
            "assert model_compass.__version__ == dist_ver, f'Compass version mismatch: {model_compass.__version__} != {dist_ver}'; "
            "assert model_analytics.__version__ == dist_ver, f'Analytics version mismatch: {model_analytics.__version__} != {dist_ver}'; "
            "print('Imports and version match dist metadata:', dist_ver)"
        )
        res_import = subprocess.run(
            [str(venv_python), "-c", verify_code],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res_import.returncode != 0:
            print("STDERR:", res_import.stderr)
            raise RuntimeError(f"Import verification failed with exit code {res_import.returncode}")

        # 2. Smoke check: model-analytics version & --help
        print("  Checking model-analytics CLI...")
        res_ana_ver = subprocess.run(
            [str(venv_analytics), "version"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res_ana_ver.returncode != 0:
            print("STDERR:", res_ana_ver.stderr)
            raise RuntimeError(f"'model-analytics version' failed with exit code {res_ana_ver.returncode}")

        res_ana_help = subprocess.run(
            [str(venv_analytics), "--help"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res_ana_help.returncode != 0:
            print("STDERR:", res_ana_help.stderr)
            raise RuntimeError(f"'model-analytics --help' failed with exit code {res_ana_help.returncode}")

        # 3. Smoke check: model-compass version & --help
        print("  Checking model-compass CLI...")
        res_comp_ver = subprocess.run(
            [str(venv_compass), "version"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res_comp_ver.returncode != 0:
            print("STDERR:", res_comp_ver.stderr)
            raise RuntimeError(f"'model-compass version' failed with exit code {res_comp_ver.returncode}")

        res_comp_help = subprocess.run(
            [str(venv_compass), "--help"],
            cwd=str(work_dir),
            capture_output=True,
            text=True,
            check=False,
        )
        if res_comp_help.returncode != 0:
            print("STDERR:", res_comp_help.stderr)
            raise RuntimeError(f"'model-compass --help' failed with exit code {res_comp_help.returncode}")

    print("All smoke checks passed successfully!")


def shutil_which(cmd: str) -> Optional[str]:
    """Resolve executable path using shutil.which if available."""
    return shutil.which(cmd)


def main() -> int:
    """Entry point for parsing CLI arguments and executing smoke checks."""
    parser = argparse.ArgumentParser(description="Smoke install and validate distribution artifacts.")
    parser.add_argument("--dist-dir", type=Path, default=Path("dist"), help="Directory containing built artifacts")
    parser.add_argument("--wheel", type=Path, default=None, help="Specific wheel file to inspect and install")
    parser.add_argument("--sdist", type=Path, default=None, help="Specific sdist file to inspect")
    parser.add_argument("--skip-install", action="store_true", help="Skip the isolated venv smoke install")
    args = parser.parse_args()

    dist_dir = args.dist_dir
    wheel_path = args.wheel
    sdist_path = args.sdist

    if wheel_path is None and dist_dir.exists():
        wheels = sorted(dist_dir.glob("*.whl"))
        if wheels:
            wheel_path = wheels[-1]

    if sdist_path is None and dist_dir.exists():
        sdists = sorted(dist_dir.glob("*.tar.gz"))
        if sdists:
            sdist_path = sdists[-1]

    if sdist_path:
        inspect_sdist(sdist_path)
    else:
        print("Notice: No sdist found to inspect.")

    if wheel_path:
        inspect_wheel(wheel_path)
        if not args.skip_install:
            smoke_install(wheel_path)
    else:
        print("Notice: No wheel found to inspect or smoke install.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
