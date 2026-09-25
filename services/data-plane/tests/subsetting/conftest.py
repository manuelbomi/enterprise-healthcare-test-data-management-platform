"""Shared fixtures for `tests/subsetting`.

Mirrors `tests/discovery/test_scanner_against_real_estate.py` and
`tests/masking/test_dataset_masker_against_real_estate.py`'s pattern: a
single, session-scoped real `tiny`-scale estate generated once on disk and
reused read-only across every test in this directory, so subsetting is
exercised against real generated data (real edge cases included), not
hand-built fixtures, without regenerating it dozens of times.
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
    output_root = tmp_path_factory.mktemp("subsetting-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root
