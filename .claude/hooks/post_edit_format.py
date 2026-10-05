#!/usr/bin/env python3
"""PostToolUse / Write|Edit|MultiEdit.

After Claude writes a file we (a) auto-format Python with the project formatter
``ruff format`` plus an import-safe ``ruff check --fix``, and (b) append the
changed path to .claude/logs/edits.log.

The formatter is detected from pyproject.toml: this project standardises on
ruff (see [tool.ruff]); there is no Black or Prettier config. Formatting failures
never block - they exit 0 with a note so a transient tooling issue cannot wedge
the session.
"""

from __future__ import annotations

import subprocess
import sys

from _common import REPO_ROOT, allow, append_log, edited_path, read_event


def _run_ruff(args: list[str]) -> None:
    try:
        subprocess.run(
            ["ruff", *args],
            cwd=str(REPO_ROOT),
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        sys.stderr.write(f"post_edit_format: ruff unavailable ({exc}); skipped.\n")


def main() -> None:
    event = read_event()
    target = edited_path(event)
    if target is None:
        allow()

    rel = target
    try:
        rel = target.relative_to(REPO_ROOT)
    except ValueError:
        pass
    append_log("edits.log", f"edited {rel}")

    if target.suffix == ".py" and target.exists():
        _run_ruff(["format", str(target)])
        _run_ruff(["check", "--fix", "--quiet", str(target)])

    allow()


if __name__ == "__main__":
    main()
