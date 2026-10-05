#!/usr/bin/env python3
"""PostToolUse / Write|Edit on dependency manifests - dependency audit trigger.

When pyproject.toml / uv.lock / requirements*.txt is edited, this hook runs
a best-effort vulnerability + license audit and records the result to
.claude/logs/dep-audit.log. It is advisory (never blocks): the authoritative,
deeper audit is the /dep-audit skill which delegates to the background-reviewer.

Audit chain (first available wins): ``pip-audit`` -> ``uv`` tree. Absence of
tooling is logged, not fatal.
"""

from __future__ import annotations

import subprocess

from _common import REPO_ROOT, allow, append_log, edited_path, read_event

MANIFESTS = {"pyproject.toml", "uv.lock", "requirements.txt", "requirements-dev.txt"}


def _try(cmd: list[str]) -> tuple[bool, str]:
    try:
        proc = subprocess.run(cmd, cwd=str(REPO_ROOT), capture_output=True, text=True, timeout=180, check=False)
        return proc.returncode == 0, (proc.stdout + proc.stderr).strip()
    except (FileNotFoundError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)


def main() -> None:
    event = read_event()
    target = edited_path(event)
    if target is None or target.name not in MANIFESTS:
        allow()

    append_log("dep-audit.log", f"manifest changed: {target.name}; running pip-audit")
    ok, out = _try(["pip-audit", "--progress-spinner", "off"])
    if ok:
        append_log("dep-audit.log", "pip-audit: no known vulnerabilities")
    else:
        tail = "\n".join(out.splitlines()[-15:]) if out else "(pip-audit unavailable)"
        append_log("dep-audit.log", f"pip-audit findings / unavailable:\n{tail}")
    append_log(
        "dep-audit.log",
        "Advisory only. Run /dep-audit for the full CVE + license review.",
    )
    allow()


if __name__ == "__main__":
    main()
