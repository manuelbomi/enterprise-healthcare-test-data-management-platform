"""Shared fixtures for `tests/benchmarks`.

`spark` is session-scoped for the same reason
`tests/spark/conftest.py::spark` is (JVM startup cost); it is a small,
deliberate duplication of that fixture rather than a cross-package
import, following this repository's existing per-subpackage `conftest.py`
convention (see `tests/capacity/conftest.py`, `tests/certification/conftest.py`,
none of which share fixtures across directories either).

`generated` runs the real `benchmark_dataset_generation` once per test
module against the `tiny` scale profile (fast enough for a unit-test
suite) and hands back the working directory and estate root every other
test in this module needs.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from data_plane.benchmarks.harness import BenchmarkResult, benchmark_dataset_generation
from data_plane.spark.session import get_local_spark_session, stop_spark_session


@pytest.fixture(scope="session")
def spark() -> Iterator[SparkSession]:
    session = get_local_spark_session("data_plane-benchmarks-tests")
    yield session
    stop_spark_session(session)


@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> tuple[Path, Path, BenchmarkResult]:
    work_dir = tmp_path_factory.mktemp("benchmarks-tiny")
    estate_root = work_dir / "estate"
    _written, bm = benchmark_dataset_generation("tiny", estate_root, seed=20240101)
    return work_dir, estate_root, bm
