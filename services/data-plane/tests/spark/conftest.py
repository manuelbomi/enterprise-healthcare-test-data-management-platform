"""Shared fixtures for `tests/spark`.

`spark` is session-scoped and shared across every test in this
directory -- constructing a `SparkSession` starts a JVM, which is slow
(multiple seconds) relative to everything else in this test suite; per
`CONTRIBUTING.md`'s "test" step, that cost should be paid once, not once
per test. `real_estate`/`claims_warehouse_root` mirror
`tests/capacity/conftest.py`'s session-scoped real-`tiny`-estate pattern.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES
from data_plane.spark.session import get_local_spark_session, stop_spark_session


@pytest.fixture(scope="session")
def spark() -> Iterator[SparkSession]:
    session = get_local_spark_session("data_plane-tests")
    yield session
    stop_spark_session(session)


@pytest.fixture(scope="session")
def real_estate(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output_root = tmp_path_factory.mktemp("spark-tests-estate")
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    estate = generator.generate()
    write_estate(estate, output_root)
    return output_root


@pytest.fixture(scope="session")
def claims_warehouse_root(real_estate: Path) -> Path:
    return real_estate / "object_storage_claims_parquet" / "claims-warehouse"
