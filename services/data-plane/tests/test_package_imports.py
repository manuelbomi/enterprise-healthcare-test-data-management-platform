"""Phase 0 smoke test: confirm the data-plane package structure imports
cleanly. No jobs exist yet to test behaviorally (see ROADMAP.md Phases
6-13); this guards against the scaffold itself being broken.

Phase 1 addition: ``data_plane.reference_data`` is real, working code
(the synthetic healthcare data estate -- see
``src/data_plane/reference_data/README.md``), so it is included here
alongside the still-placeholder modules.
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
        "data_plane.reference_data",
    ):
        importlib.import_module(module_name)
