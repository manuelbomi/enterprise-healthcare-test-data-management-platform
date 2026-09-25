"""Real, on-disk footprint measurement tests against a real generated
`tiny`-scale estate -- no mocking of the filesystem or of pandas/pyarrow,
per `CONTRIBUTING.md`'s "data-transformation logic gets data-quality
tests" convention applied to this phase's measurement tooling.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest

from data_plane.capacity.footprint import (
    directory_size_bytes,
    measure_directory_footprint,
    measure_parquet_compression,
)


def test_directory_size_bytes_matches_sum_of_real_file_sizes(real_estate: Path) -> None:
    expected = sum(f.stat().st_size for f in real_estate.rglob("*") if f.is_file())
    assert directory_size_bytes(real_estate) == expected
    assert expected > 0


def test_directory_size_bytes_of_missing_path_is_zero(tmp_path: Path) -> None:
    assert directory_size_bytes(tmp_path / "does-not-exist") == 0


def test_measure_parquet_compression_against_a_real_parquet_file(real_estate: Path) -> None:
    parquet_files = list(real_estate.rglob("*.parquet"))
    assert parquet_files, "the real tiny-scale estate must include real Parquet output (ADR-0007)"

    measurement = measure_parquet_compression(parquet_files[0])
    assert measurement.compressed_bytes == parquet_files[0].stat().st_size
    assert measurement.compressed_bytes > 0
    assert measurement.row_count > 0
    assert measurement.column_count > 0
    assert measurement.uncompressed_estimate_bytes > 0
    assert measurement.compression_ratio == pytest.approx(
        measurement.uncompressed_estimate_bytes / measurement.compressed_bytes
    )


def test_measure_parquet_compression_raises_for_missing_file(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        measure_parquet_compression(tmp_path / "nope.parquet")


def test_measure_parquet_compression_ratio_is_believable(tmp_path: Path) -> None:
    # A synthetic, deliberately repetitive frame (many identical rows) --
    # Parquet's dictionary/RLE encoding should compress well relative to
    # re-encoding the same rows as CSV, giving a ratio clearly > 1.
    frame = pd.DataFrame(
        {
            "member_id": ["SYN-MBR-000001"] * 5_000,
            "status": ["ACTIVE"] * 5_000,
            "amount": [123.45] * 5_000,
        }
    )
    path = tmp_path / "repetitive.parquet"
    frame.to_parquet(path, index=False)

    measurement = measure_parquet_compression(path)
    assert measurement.row_count == 5_000
    assert measurement.compression_ratio > 1.0


def test_measure_directory_footprint_reports_real_totals(real_estate: Path) -> None:
    report = measure_directory_footprint(real_estate)
    expected_total = sum(f.stat().st_size for f in real_estate.rglob("*") if f.is_file())
    assert report.total_bytes == expected_total
    assert report.total_file_count > 0
    assert sum(report.bytes_by_extension.values()) == report.total_bytes
    assert sum(report.file_count_by_extension.values()) == report.total_file_count


def test_measure_directory_footprint_includes_multiple_real_formats(real_estate: Path) -> None:
    # The Phase 1 estate is deliberately multi-format (ADR-0007 baseline
    # Parquet, plus SQLite/CSV/NDJSON per ARCHITECTURE.md's five
    # simulated source systems) -- a real measurement must see more than
    # one extension, not just Parquet.
    report = measure_directory_footprint(real_estate)
    assert len(report.bytes_by_extension) > 1


def test_measure_directory_footprint_aggregates_real_parquet_compression(real_estate: Path) -> None:
    report = measure_directory_footprint(real_estate)
    assert report.parquet_compression, "at least one real Parquet file must have been measured"
    assert report.total_parquet_compressed_bytes > 0
    assert report.total_parquet_uncompressed_estimate_bytes > 0
    ratio = report.overall_parquet_compression_ratio
    assert ratio is not None
    assert ratio == pytest.approx(
        report.total_parquet_uncompressed_estimate_bytes / report.total_parquet_compressed_bytes
    )
    # NOTE: at `tiny` scale (a handful of rows per file), Parquet's real,
    # measured footer/column-chunk-statistics overhead can genuinely
    # exceed its compression benefit -- ratio can legitimately be < 1.0.
    # See test_compression_ratio_improves_with_realistic_row_counts_below
    # for the real measurement at a larger, more representative scale,
    # and docs/CAPACITY_COST_TRADEOFFS.md for the honest discussion. This
    # test asserts internal consistency, not a specific direction, so it
    # never encodes a fabricated expectation about real measured data.


def test_compression_ratio_improves_with_realistic_row_counts(tmp_path: Path) -> None:
    # A real (not fabricated) demonstration that Parquet's compression
    # advantage is scale-dependent: at `tiny` scale the estate's own
    # per-file row counts are small enough that Parquet's overhead can
    # dominate (see the note above); at `developer` scale (still small,
    # but hundreds to low-thousands of rows per file) real measurement
    # shows Parquet clearly ahead of CSV. Generating the `developer`
    # profile is fast (well under a second) so this runs inline rather
    # than needing its own session fixture.
    from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
    from data_plane.reference_data.estate_writer import write_estate
    from data_plane.reference_data.generator import EstateGenerator
    from data_plane.reference_data.scale import SCALE_PROFILES

    generator = EstateGenerator(SCALE_PROFILES["developer"], DEFAULT_EDGE_CASE_CONFIG, seed=20240101)
    write_estate(generator.generate(), tmp_path)

    report = measure_directory_footprint(tmp_path)
    ratio = report.overall_parquet_compression_ratio
    assert ratio is not None
    assert ratio > 1.0, "at developer scale, real measured Parquet output should compress better than CSV"


def test_measure_directory_footprint_of_missing_path_is_empty(tmp_path: Path) -> None:
    report = measure_directory_footprint(tmp_path / "does-not-exist")
    assert report.total_bytes == 0
    assert report.total_file_count == 0
    assert report.parquet_compression == []
