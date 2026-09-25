"""Smoke tests for `scripts/security/dependency_scan.py` -- the
dependency-scanning hook Phase 11 adds (real script; CI wiring is
Phase 12's job, see `problems_phase_11.md` P11-3). These tests do not
require `pip-audit` to actually be installed -- they prove the script
behaves honestly either way (a real scan when available, an explicit,
non-zero failure when not -- never a silent skip that could be
mistaken for a clean result)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[4]
SCRIPT_PATH = REPO_ROOT / "scripts" / "security" / "dependency_scan.py"


def _load_dependency_scan():
    spec = importlib.util.spec_from_file_location("dependency_scan", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["dependency_scan"] = module
    spec.loader.exec_module(module)
    return module


def test_script_is_importable_and_exposes_the_expected_functions() -> None:
    module = _load_dependency_scan()
    assert hasattr(module, "find_pip_audit")
    assert hasattr(module, "main")
    assert len(module.PACKAGE_ROOTS) == 4


def test_main_does_not_silently_pass_when_pip_audit_is_unavailable(monkeypatch) -> None:
    module = _load_dependency_scan()
    monkeypatch.setattr(module, "find_pip_audit", lambda: None)
    exit_code = module.main()
    assert exit_code != 0  # an explicit, honest failure -- never a silent 0


def test_package_roots_all_exist_and_have_a_pyproject_toml() -> None:
    module = _load_dependency_scan()
    for package in module.PACKAGE_ROOTS:
        assert (REPO_ROOT / package / "pyproject.toml").exists(), package
