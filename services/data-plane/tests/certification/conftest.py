"""Shared fixtures for `tests/certification`.

Mirrors `tests/subsetting/conftest.py` and `tests/synthetic/conftest.py`'s
pattern: a single, session-scoped real `tiny`-scale Phase 1 estate,
generated once and reused read-only, plus fixed (not env-var-resolved)
masking and certification-signing keys so tests never depend on the
developer's shell environment.
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
    output_root = tmp_path_factory.mktemp("certification-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root


@pytest.fixture()
def masking_key() -> bytes:
    """A fixed, throwaway test key -- never the same key used anywhere
    else, never resolved from the environment (tests must not depend on
    a developer's shell having TDM_MASKING_HMAC_KEY set)."""

    return b"certification-test-masking-key-0123456789abcdef"


@pytest.fixture()
def signing_key() -> bytes:
    return b"certification-test-signing-key-fedcba9876543210"
