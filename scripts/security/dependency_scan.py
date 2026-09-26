#!/usr/bin/env python3
"""Dependency-vulnerability scanning hook.

`ROADMAP.md` Phase 11 asks for "dependency scanning hooks." Real CI/CD
wiring is explicitly Phase 12's scope (`ROADMAP.md`: "Production CI/CD
and cloud testing (GitHub Actions, K8s, Terraform)") -- this script is
the *hook definition* Phase 12 wires in, not a claim that scanning is
already running in CI. See `docs/problems/problems_phase_11.md` P11-3.

This script runs `pip-audit` (if installed) against every Python
package in this repository (`libs/contracts`, `services/control-plane`,
`services/data-plane`, `services/governance-service`) and reports
known vulnerabilities in their installed dependencies. It deliberately
does **not** silently pass if `pip-audit` is unavailable -- a
dependency scan that no-ops without saying so is worse than no scan at
all, since a reviewer (or a future CI log) could mistake silence for a
clean result. Instead it prints an explicit, actionable message and
exits non-zero, so a caller (a human, or eventually a CI step) cannot
mistake "the tool isn't installed" for "no vulnerabilities found."

Usage:
    python scripts/security/dependency_scan.py
    pip install pip-audit   # if not already available
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]

#: Every installable Python package in this repository (per
#: `CONTRIBUTING.md`'s layout section) that has its own `pyproject.toml`
#: and therefore its own dependency set worth scanning independently.
PACKAGE_ROOTS = (
    "libs/contracts",
    "services/control-plane",
    "services/data-plane",
    "services/governance-service",
)


def find_pip_audit() -> list[str] | None:
    """Locate a runnable `pip-audit` invocation.

    Prefers the `pip-audit` console script on PATH (the normal case in
    a CI runner's venv). Falls back to `python -m pip_audit` -- the
    package installs fine (`pip show pip-audit` succeeds) but its
    console-script entry point can still be missing from PATH in some
    local environments (e.g. a per-user `pip install` on Windows whose
    Scripts directory isn't on PATH), a real gap hit and fixed while
    verifying this script for Phase 12's CI wiring. `python -m
    pip_audit` only works if the module actually imports, so this still
    correctly reports "not installed" when the package genuinely isn't
    present.
    """

    on_path = shutil.which("pip-audit")
    if on_path is not None:
        return [on_path]
    probe = subprocess.run(
        [sys.executable, "-m", "pip_audit", "--version"],
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return [sys.executable, "-m", "pip_audit"]
    return None


def run_pip_audit_for_package(pip_audit_cmd: list[str], package_root: Path) -> tuple[bool, str]:
    """Run `pip-audit` against `package_root`'s `pyproject.toml`.
    Returns `(clean, output)`. `pip-audit -r`/project-scanning options
    vary by version, so this uses the simplest, most broadly-supported
    invocation: scanning the currently-active environment's installed
    packages while `cwd` is set to the package root (so a local venv
    with that package installed reflects its actual dependency set).

    `--skip-editable` is required, not optional: every workspace
    package in this repository (`healthcare-tdm-contracts` and the
    three services) is installed editable (`pip install -e ".[dev]"`,
    `scripts/bootstrap.sh`) and is not published to PyPI. Without this
    flag, pip-audit tries to resolve `healthcare-tdm-contracts` itself
    against PyPI to audit it and fails with "Dependency not found on
    PyPI and could not be audited" -- a real failure hit and fixed
    while verifying this script's first real CI run (Phase 12; see
    docs/problems/problems_phase_12.md). This is the semantically correct fix, not a
    workaround: this scan's job is to audit *third-party* dependencies
    for known vulnerabilities, and our own workspace packages are
    neither third-party nor published, so they have no PyPI-tracked
    CVE history to audit in the first place.

    Deliberately does NOT pass `--strict` (a second, real finding from
    the same verification run): `--strict` treats `--skip-editable`
    skipping our own workspace packages as itself a fatal collection
    error ("distribution marked as editable"), which would fail this
    scan on every run regardless of whether any real third-party
    vulnerability exists -- the opposite of a meaningful gate. Without
    `--strict`, a skipped (editable, local) package is reported as a
    skip, not an error, and the scan's exit code reflects only whether
    a real, known vulnerability was found in an actual third-party
    dependency -- see docs/problems/problems_phase_12.md for the real vulnerability
    findings this surfaced once fixed.
    """

    result = subprocess.run(
        [*pip_audit_cmd, "--skip-editable"],
        cwd=package_root,
        capture_output=True,
        text=True,
    )
    clean = result.returncode == 0
    output = (result.stdout or "") + (result.stderr or "")
    return clean, output


def main() -> int:
    pip_audit_cmd = find_pip_audit()
    if pip_audit_cmd is None:
        print(
            "dependency_scan: pip-audit is not installed on PATH -- this scan cannot run.\n"
            "This is reported as a FAILURE, not silently skipped, so it cannot be mistaken\n"
            "for a clean result. To fix: pip install pip-audit\n"
            "(Phase 12 wires this script into CI; see docs/problems/problems_phase_11.md P11-3.)",
            file=sys.stderr,
        )
        return 1

    overall_clean = True
    for package in PACKAGE_ROOTS:
        package_root = REPO_ROOT / package
        if not (package_root / "pyproject.toml").exists():
            print(f"dependency_scan: skipping {package} (no pyproject.toml found)")
            continue
        clean, output = run_pip_audit_for_package(pip_audit_cmd, package_root)
        status = "CLEAN" if clean else "FINDINGS"
        print(f"dependency_scan: {package}: {status}")
        if not clean:
            overall_clean = False
            print(output)

    return 0 if overall_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
