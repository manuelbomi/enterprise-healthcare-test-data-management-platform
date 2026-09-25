#!/usr/bin/env python3
"""Dependency-vulnerability scanning hook.

`ROADMAP.md` Phase 11 asks for "dependency scanning hooks." Real CI/CD
wiring is explicitly Phase 12's scope (`ROADMAP.md`: "Production CI/CD
and cloud testing (GitHub Actions, K8s, Terraform)") -- this script is
the *hook definition* Phase 12 wires in, not a claim that scanning is
already running in CI. See `problems_phase_11.md` P11-3.

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


def find_pip_audit() -> str | None:
    return shutil.which("pip-audit")


def run_pip_audit_for_package(pip_audit_path: str, package_root: Path) -> tuple[bool, str]:
    """Run `pip-audit` against `package_root`'s `pyproject.toml`.
    Returns `(clean, output)`. `pip-audit -r`/project-scanning options
    vary by version, so this uses the simplest, most broadly-supported
    invocation: scanning the currently-active environment's installed
    packages while `cwd` is set to the package root (so a local venv
    with that package installed reflects its actual dependency set).
    """

    result = subprocess.run(
        [pip_audit_path, "--strict"],
        cwd=package_root,
        capture_output=True,
        text=True,
    )
    clean = result.returncode == 0
    output = (result.stdout or "") + (result.stderr or "")
    return clean, output


def main() -> int:
    pip_audit_path = find_pip_audit()
    if pip_audit_path is None:
        print(
            "dependency_scan: pip-audit is not installed on PATH -- this scan cannot run.\n"
            "This is reported as a FAILURE, not silently skipped, so it cannot be mistaken\n"
            "for a clean result. To fix: pip install pip-audit\n"
            "(Phase 12 wires this script into CI; see problems_phase_11.md P11-3.)",
            file=sys.stderr,
        )
        return 1

    overall_clean = True
    for package in PACKAGE_ROOTS:
        package_root = REPO_ROOT / package
        if not (package_root / "pyproject.toml").exists():
            print(f"dependency_scan: skipping {package} (no pyproject.toml found)")
            continue
        clean, output = run_pip_audit_for_package(pip_audit_path, package_root)
        status = "CLEAN" if clean else "FINDINGS"
        print(f"dependency_scan: {package}: {status}")
        if not clean:
            overall_clean = False
            print(output)

    return 0 if overall_clean else 1


if __name__ == "__main__":
    raise SystemExit(main())
