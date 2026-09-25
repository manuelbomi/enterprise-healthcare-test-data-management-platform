"""Storage and compute footprint measurement (Phase 8) -- the data-plane
half of capacity planning, per `docs/adr/0013-capacity-planning-plane-split.md`.

Module map
----------
- `footprint.py` -- real, on-disk directory/Parquet size measurement
  (`measure_directory_footprint`, `measure_parquet_compression`).
- `partitioning.py` -- real, on-disk Hive-style partition layout
  analysis (`analyze_partitions`).
- `incremental.py` -- a modeled (not measured) illustration of what an
  incremental refresh would have saved relative to Phase 7's actual
  full-reprocessing `refresh()` (`estimate_incremental_savings`).

Everything here operates on filesystem paths or already-registered
`healthcare_tdm_contracts` shapes, exactly like every other data-plane
engine (`data_plane.discovery`, `data_plane.subsetting`, ...) -- it never
imports `control_plane`. The control-plane half,
`control_plane.domain.capacity`, aggregates these (or the `size_bytes`/
`row_counts` a caller measured with them) across registered dataset
versions and environment requests; see this package's README for the
full split.
"""

from data_plane.capacity.footprint import (
    directory_size_bytes,
    measure_directory_footprint,
    measure_parquet_compression,
)
from data_plane.capacity.incremental import estimate_incremental_savings
from data_plane.capacity.partitioning import analyze_partitions

__all__ = [
    "analyze_partitions",
    "directory_size_bytes",
    "estimate_incremental_savings",
    "measure_directory_footprint",
    "measure_parquet_compression",
]
