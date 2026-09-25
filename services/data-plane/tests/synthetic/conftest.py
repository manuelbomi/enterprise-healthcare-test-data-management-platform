"""Shared fixtures for `tests/synthetic`.

Mirrors `tests/subsetting/conftest.py`'s pattern: a single, session-scoped
real `tiny`-scale Phase 1 estate, generated once and reused read-only,
plus a session-scoped Phase 4 subset of it (this phase's "augment mode"
input in the real, intended pipeline shape: masked/subsetted output ->
this phase augments it with scenarios).
"""

from __future__ import annotations

from pathlib import Path

import pytest
from healthcare_tdm_contracts import SubsettingStrategy

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES
from data_plane.subsetting.engine import run_subsetting


@pytest.fixture(scope="session")
def real_estate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("synthetic-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root


@pytest.fixture(scope="session")
def subset_estate(real_estate: Path, tmp_path_factory: pytest.TempPathFactory) -> Path:
    """A real Phase 4 subset (stand-in for a "subsetted-and-masked"
    pipeline output) -- this phase's intended "augment mode" input."""

    out_dir = tmp_path_factory.mktemp("synthetic-base-subset")
    run_subsetting(real_estate, out_dir, SubsettingStrategy.FIXED_POPULATION, {"count": "10"})
    return out_dir
