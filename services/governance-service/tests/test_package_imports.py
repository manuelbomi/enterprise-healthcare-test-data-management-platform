"""Phase 0 smoke test: confirm the governance-service package structure
imports cleanly. Behavioral tests are added in Phase 3.
"""

from __future__ import annotations

import importlib


def test_all_governance_service_submodules_import() -> None:
    for module_name in (
        "governance_service",
        "governance_service.api",
        "governance_service.audit",
    ):
        importlib.import_module(module_name)
