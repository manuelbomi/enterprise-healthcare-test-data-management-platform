"""Shared fixtures for `tests/capacity`. Mirrors
`tests/certification/conftest.py`'s pattern: a single, session-scoped
real `tiny`-scale Phase 1 estate, generated once and reused read-only,
so this module's real footprint/compression measurements run against
real, on-disk Parquet/CSV/NDJSON/SQLite output rather than a fixture
that only pretends to be a multi-format estate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES


@pytest.fixture(scope="session")
def real_estate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("capacity-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root
