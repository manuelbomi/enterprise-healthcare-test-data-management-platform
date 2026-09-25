"""Phase 0 smoke test: confirm the data-plane package structure imports
cleanly. No jobs exist yet to test behaviorally (see ROADMAP.md Phases
6-13); this guards against the scaffold itself being broken.
"""

from __future__ import annotations

import importlib


def test_all_data_plane_submodules_import() -> None:
    for module_name in (
        "data_plane",
        "data_plane.discovery",
        "data_plane.subsetting",
        "data_plane.masking",
        "data_plane.synthetic",
        "data_plane.jobs",
    ):
        importlib.import_module(module_name)
