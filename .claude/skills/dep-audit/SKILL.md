---
name: dep-audit
description: Dependency audit for ModelCompass. Invoke on changes to pyproject.toml / uv.lock / requirements.txt, or on a weekly cadence, or manually as /dep-audit. Runs a CVE scan and a license-compatibility check and delegates the deep write-up to the background-reviewer agent.
allowed-tools: Read, Grep, Glob, Bash, Agent
invocation: /dep-audit
---

# Dependency Audit

Audit Python dependencies for known CVEs and license conflicts. (A lightweight
advisory pass also runs automatically via the `dep_audit.py` PostToolUse hook
when a manifest changes; this skill is the authoritative deep version.)

## Steps

1. **Vulnerabilities**:
   - `uv run pip-audit --progress-spinner off` (or `pip-audit` directly).
   - For each finding, note package, installed version, CVE/GHSA id, fixed
     version, and severity.
2. **Outdated pins**: `uv tree --outdated` - flag majors behind that carry
   security relevance.
3. **Licences**: enumerate direct deps from `pyproject.toml`; identify each
   license (use `pip-licenses` if available, else WebSearch). Classify each into
   Allow / Flag / Block using
   **[references/license-policy.md](references/license-policy.md)** — under the
   default proprietary-distribution policy, GPL/AGPL/SSPL and unknown licenses are
   blocking and LGPL/MPL are flags needing sign-off; adjust the policy doc if your
   project's licensing model differs.
4. **Delegate the report**: spawn the `background-reviewer` agent to compile the
   findings into `docs/reviews/YYYY-MM-DD-dep-audit.md` with severities and
   recommended bumps.

## Output

```
## Dependency Audit - <date>
### Vulnerabilities
| Package | Version | CVE/GHSA | Severity | Fixed in |
### Licence risks
| Package | Licence | Risk |
### Recommended actions (for coder)
- bump <pkg> <old> → <new>
```
If any CRITICAL/HIGH CVE is found, recommend an immediate `python-expert` bump + `testing-expert`
regression run before the next release.

## Completion checklist

- [ ] `pip-audit` run; every finding has package, version, CVE/GHSA id, severity, and fixed-in version
- [ ] `uv tree --outdated` reviewed; security-relevant majors-behind flagged
- [ ] Every direct dep license classified Allow / Flag / Block per [references/license-policy.md](references/license-policy.md)
- [ ] Any GPL/AGPL/SSPL/unknown license reported as a **blocking** risk with a proposed remedy
- [ ] `UNKNOWN`/unclassified licenses reported explicitly - not silently omitted
- [ ] `background-reviewer` spawned to compile `docs/reviews/YYYY-MM-DD-dep-audit.md`
- [ ] Any CRITICAL/HIGH CVE → immediate `python-expert` bump + `testing-expert` regression recommended
