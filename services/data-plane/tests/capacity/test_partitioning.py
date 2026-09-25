"""Real, on-disk partition-layout analysis tests. `write_claims_warehouse`
(`data_plane.reference_data.writers.parquet_writer`) deliberately writes
`claim/batch=claims-2024Q4/` and `claim/batch=claims-2025Q1/` as two real
Hive-style partitions -- this module analyzes exactly that real layout,
not a hand-built fixture.
"""

from __future__ import annotations

from pathlib import Path

from data_plane.capacity.partitioning import analyze_partitions


def _claims_warehouse_root(real_estate: Path) -> Path:
    return real_estate / "object_storage_claims_parquet" / "claims-warehouse"


def test_analyze_partitions_finds_the_real_batch_partitions(real_estate: Path) -> None:
    claim_dir = _claims_warehouse_root(real_estate) / "claim"
    summary = analyze_partitions(claim_dir)

    assert summary.partition_key == "batch"
    assert summary.partition_count >= 1
    assert sum(summary.bytes_by_partition.values()) > 0
    for value, size in summary.bytes_by_partition.items():
        assert value.startswith("claims-")
        assert size > 0


def test_analyze_partitions_of_unpartitioned_directory_reports_none(real_estate: Path) -> None:
    # claim_line/ is written as a single flat file, no batch= segment.
    claim_line_dir = _claims_warehouse_root(real_estate) / "claim_line"
    summary = analyze_partitions(claim_line_dir)
    assert summary.partition_key is None
    assert summary.partition_count == 0


def test_analyze_partitions_of_missing_path_is_empty(tmp_path: Path) -> None:
    summary = analyze_partitions(tmp_path / "does-not-exist")
    assert summary.partition_key is None
    assert summary.partition_count == 0
