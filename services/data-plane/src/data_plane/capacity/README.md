# `data_plane.capacity` — real footprint measurement (Phase 8)

The data-plane half of capacity planning: real, on-disk measurement,
never estimation or configuration. See
[ADR-0013](../../../../../docs/adr/0013-capacity-planning-plane-split.md)
for why this is split from `control_plane.domain.capacity` (which
aggregates already-registered numbers across dataset versions and
environments) rather than one module doing both.

## Module map

| Module | Responsibility |
|---|---|
| `footprint.py` | `measure_directory_footprint` — real total bytes, per-extension breakdown, and real Parquet-vs-re-encoded-CSV compression measurement for every `.parquet` file found. |
| `partitioning.py` | `analyze_partitions` — real, on-disk Hive-style (`key=value`) partition layout analysis. |
| `incremental.py` | `estimate_incremental_savings` — a *modeled* (not measured) illustration of what an incremental refresh would have saved relative to Phase 7's actual full-reprocessing `refresh()`. |
| `cli.py` | `python -m data_plane.capacity.cli footprint <path>` / `partitions <path>`. |

## What is real here, and what is modeled

- **Real:** `directory_size_bytes`, `measure_directory_footprint`, and
  `measure_parquet_compression` read actual bytes off actual files. Run
  them against any real output this platform already produces (a
  `data_plane.reference_data` estate, a `data_plane.certification`
  pipeline's `final/` directory, ...) and you get real numbers, not
  fabricated ones. `analyze_partitions` reads the real Hive-style
  partition directories `data_plane.reference_data.writers.parquet_writer`
  already writes.
- **Modeled:** `estimate_incremental_savings` computes real arithmetic
  (a row-count delta between two real `DatasetVersion`s) but reports
  what an incremental-refresh *engine that does not exist in this
  repository* would plausibly have saved — it is a documented
  illustration of an unbuilt capability, not a claim that this platform
  does incremental refresh today. See
  [`docs/CAPACITY_COST_TRADEOFFS.md`](../../../../../docs/CAPACITY_COST_TRADEOFFS.md).

## Running it

```bash
# From services/data-plane, with the package installed (pip install -e .):

# Measure the real footprint of a generated estate or pipeline output:
python -m data_plane.capacity.cli footprint data/tmp/synthetic-estate

# Analyze the real partition layout of the claims warehouse extract:
python -m data_plane.capacity.cli partitions \
    "data/tmp/synthetic-estate/object_storage_claims_parquet/claims-warehouse/claim"
```

See `scripts/demo_phase8_capacity.py` for an end-to-end run that
measures a real certification pipeline's output with this module and
feeds the result into `control_plane.domain.capacity.CapacityPlanner`.
