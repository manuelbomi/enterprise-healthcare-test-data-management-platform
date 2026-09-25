"""Real benchmark-function tests against a real, generated `tiny`-scale
estate -- every `benchmark_*` function is exercised against real output
its own underlying Phase 1/3/4/8/14 engine produced, per
`CONTRIBUTING.md`'s data-quality-test convention. Assertions are
structural (positive throughput, correct row counts, real bytes on disk)
-- never a hardcoded "expected number", since a benchmark's whole point
is to measure whatever this run's real numbers actually are.
"""

from __future__ import annotations

from pathlib import Path

from pyspark.sql import SparkSession

from data_plane.benchmarks.harness import (
    BenchmarkResult,
    benchmark_pandas_masking,
    benchmark_pandas_masking_validation,
    benchmark_pandas_subsetting,
    benchmark_spark_masking,
    benchmark_spark_subsetting,
    benchmark_storage_footprint,
    build_catalog_for_estate,
)
from data_plane.capacity.footprint import directory_size_bytes

TEST_KEY = b"benchmarks-test-hmac-key-0123456789abcdef"

Generated = tuple[Path, Path, BenchmarkResult]


def test_benchmark_dataset_generation_reports_positive_throughput(generated: Generated) -> None:
    _work_dir, _estate_root, bm = generated
    assert bm.rows > 0
    assert bm.elapsed_seconds > 0
    assert bm.records_per_second() > 0
    assert bm.extra["scale_profile"] == "tiny"
    assert bm.extra["files_written"] > 0


def test_benchmark_storage_footprint_matches_real_bytes(generated: Generated) -> None:
    _work_dir, estate_root, _bm = generated
    footprint_bm = benchmark_storage_footprint(estate_root)
    assert footprint_bm.rows > 0
    assert footprint_bm.extra["total_bytes"] == directory_size_bytes(estate_root)
    assert footprint_bm.extra["total_bytes"] > 0
    # The tiny estate's claim/claim_line/diagnosis/procedure tables are
    # real Parquet (ADR-0007) -- at least one compression measurement
    # must have been taken.
    assert footprint_bm.extra["parquet_files_measured"] > 0
    assert footprint_bm.extra["mean_parquet_compression_ratio"] > 0


def test_benchmark_storage_footprint_of_missing_directory_is_zero(tmp_path: Path) -> None:
    bm = benchmark_storage_footprint(tmp_path / "does-not-exist")
    assert bm.rows == 0
    assert bm.extra["total_bytes"] == 0
    assert bm.extra["mean_parquet_compression_ratio"] is None


def test_benchmark_pandas_masking_and_validation(generated: Generated, tmp_path: Path) -> None:
    _work_dir, estate_root, _bm = generated
    catalog_entries = build_catalog_for_estate(estate_root)

    report, masking_bm = benchmark_pandas_masking(
        estate_root, catalog_entries, tmp_path / "masked", key=TEST_KEY
    )
    assert masking_bm.rows == report.rows_processed
    assert masking_bm.rows > 0
    assert masking_bm.elapsed_seconds > 0
    assert masking_bm.records_per_second() > 0

    validation, validation_bm = benchmark_pandas_masking_validation(report)
    assert validation.passed is True
    assert validation_bm.extra["passed"] is True
    assert "referential_integrity" in validation.checks_run


def test_benchmark_pandas_subsetting(generated: Generated, tmp_path: Path) -> None:
    _work_dir, estate_root, _bm = generated
    # `tiny` scale has only 25 members -- a large percentage keeps the
    # selection non-empty and the test deterministic.
    result, bm = benchmark_pandas_subsetting(
        estate_root, tmp_path / "subset", percentage=50.0, seed=20240101
    )
    assert bm.extra["selected_member_count"] > 0
    assert bm.extra["selected_member_count"] <= bm.extra["source_member_count"]
    assert result.validation.passed


def test_benchmark_spark_masking(spark: SparkSession, generated: Generated, tmp_path: Path) -> None:
    _work_dir, estate_root, _bm = generated
    claims_root = estate_root / "object_storage_claims_parquet" / "claims-warehouse"
    result, bm = benchmark_spark_masking(spark, claims_root, tmp_path / "spark-masked", key=TEST_KEY)
    assert bm.rows == result.rows_written
    assert bm.rows > 0
    assert bm.records_per_second() > 0
    assert bm.extra["columns_masked"] == ["member_id", "claim_id"]


def test_benchmark_spark_subsetting(spark: SparkSession, generated: Generated, tmp_path: Path) -> None:
    _work_dir, estate_root, _bm = generated
    claims_root = estate_root / "object_storage_claims_parquet" / "claims-warehouse"
    result, bm = benchmark_spark_subsetting(
        spark, claims_root, tmp_path / "spark-subset", member_fraction=0.5, seed=20240101
    )
    assert bm.extra["members_sampled"] > 0
    assert bm.extra["claim_lines_output_rows"] == result.claim_lines_output_rows
    assert 0.0 <= bm.extra["selectivity"] <= 1.0
