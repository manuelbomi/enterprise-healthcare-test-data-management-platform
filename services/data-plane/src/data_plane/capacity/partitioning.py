"""Real, on-disk partition-layout analysis (Phase 8).

`ROADMAP.md` Phase 8 asks the platform to "design mechanisms
demonstrating ... partitioning." This platform already writes real
Hive-style partitions -- see
`data_plane.reference_data.writers.parquet_writer.write_claims_warehouse`,
which deliberately writes `claim/batch=claims-2024Q4/` and
`claim/batch=claims-2025Q1/` as two separate partitions (its own
docstring explains this simulates a real claims-warehouse ETL schema
change between quarters). This module does not invent new
infrastructure to "demonstrate" partitioning -- it analyzes the
partitioning that is already real and already on disk, the same
honest-measurement principle `footprint.py` follows for compression.
"""

from __future__ import annotations

import re
from pathlib import Path

from healthcare_tdm_contracts import PartitionSummary

#: Matches a single Hive-style partition directory segment, e.g. `batch=claims-2025Q1`.
_PARTITION_SEGMENT = re.compile(r"^([A-Za-z0-9_]+)=(.+)$")


def analyze_partitions(root: Path) -> PartitionSummary:
    """Scan every file under `root` for a Hive-style `key=value` path
    segment (e.g. `.../claim/batch=claims-2025Q1/part-0000.parquet`) and
    report real, on-disk bytes/file-count per partition value.

    If more than one distinct partition *key* name is found under
    `root` (unusual, but possible in a directory tree spanning multiple
    datasets), only the first key encountered (by directory walk order)
    is reported -- callers that need per-dataset partitioning should
    call this once per dataset subdirectory, which is how
    `data_plane.capacity.cli` and this phase's own tests use it.
    """

    if not root.exists():
        return PartitionSummary(root_path=str(root), partition_key=None, partition_count=0)

    bytes_by_partition: dict[str, int] = {}
    count_by_partition: dict[str, int] = {}
    partition_key: str | None = None

    for f in root.rglob("*"):
        if not f.is_file():
            continue
        for part in f.relative_to(root).parts[:-1]:
            match = _PARTITION_SEGMENT.match(part)
            if not match:
                continue
            key, value = match.group(1), match.group(2)
            if partition_key is None:
                partition_key = key
            if key != partition_key:
                continue
            size = f.stat().st_size
            bytes_by_partition[value] = bytes_by_partition.get(value, 0) + size
            count_by_partition[value] = count_by_partition.get(value, 0) + 1

    return PartitionSummary(
        root_path=str(root),
        partition_key=partition_key,
        partition_count=len(bytes_by_partition),
        bytes_by_partition=bytes_by_partition,
        file_count_by_partition=count_by_partition,
    )


__all__ = ["analyze_partitions"]
