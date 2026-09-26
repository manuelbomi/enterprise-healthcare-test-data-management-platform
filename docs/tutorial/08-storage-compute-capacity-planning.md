# Tutorial 08 — Storage and compute capacity planning

This tutorial walks through real, runnable code:
`data_plane.capacity` (real, on-disk footprint measurement) and
`control_plane.domain.capacity` (real, DB-backed capacity planning over
Phase 7's dataset versions and environment requests), exposed at
`/api/v1/capacity`. Read
[`docs/CAPACITY_COST_TRADEOFFS.md`](../CAPACITY_COST_TRADEOFFS.md) before
treating any number this phase produces as more precise than it actually
is -- it documents, honestly, which numbers are real measurements, which
are real aggregations of already-registered data, and which are
configurable illustrations.

## Why this is two packages, not one

`ROADMAP.md` Phase 8 asks for two genuinely different things: *measuring*
real bytes off real files (only meaningful against a real directory on
disk), and *planning* capacity across dataset versions and environments
Phase 7 already tracks (only meaningful against the metadata plane's
database). Mixing them into one module would mean either the data plane
reaching into the control plane's database, or the control plane
reaching into object storage directly -- both violate ADR-0003's plane
separation. See
[ADR-0013](../adr/0013-capacity-planning-plane-split.md) for the full
reasoning behind the split, and `scripts/demo_phase8_capacity.py` for the
standalone glue script (same shape as Phase 7's demo script) that ties
both together for this walkthrough.

## What Phase 7 already solved, and what this phase adds

Phase 7 already made "avoid unnecessary duplicate physical copies" real:
`EnvironmentDatasetRequest.current_version_id` is a foreign key to one
immutable `DatasetVersion`, never a copy. This phase does not re-solve
that -- it makes the *savings* from that architecture a concrete,
computed number (`CapacityPlan.naive_total_storage_bytes` vs.
`shared_total_storage_bytes`), and adds real footprint measurement,
compute-demand estimation, vacuum-candidate identification, and a
configurable illustrative percentage-of-production model on top of it.

## The shapes

All defined in `healthcare_tdm_contracts.capacity`
(`libs/contracts/src/healthcare_tdm_contracts/capacity.py`):

| Contract | Real or modeled? | Produced by |
|---|---|---|
| `CompressionMeasurement` / `FootprintMeasurementReport` | Real, on-disk | `data_plane.capacity.footprint` |
| `PartitionSummary` | Real, on-disk | `data_plane.capacity.partitioning` |
| `DatasetVersionFootprint` / `EnvironmentCapacityDemand` / `CapacityPlan` / `VacuumCandidate` | Real, DB-backed | `control_plane.domain.capacity.CapacityPlanner` |
| `IncrementalRefreshEstimate` | Modeled (real row-count deltas, hypothetical savings) | `data_plane.capacity.incremental` |
| `EnvironmentCapacityRequirement` / `IllustrativeCapacityScenario` / `IllustrativeCapacityPlan` | Illustrative (configurable) | `control_plane.domain.capacity.illustrative_capacity_plan` |

## Try it yourself: a real, end-to-end run

```bash
python scripts/demo_phase8_capacity.py
```

Real output from exactly this command (a `developer`-scale certification
pipeline run, chosen because it's fast *and* large enough — hundreds of
rows per file — for real Parquet compression to actually pay off; see
`docs/CAPACITY_COST_TRADEOFFS.md` section 2 for why `tiny` scale would
show the opposite):

```
STEP 1 -- Real certification pipeline run (developer scale)
Certification status: PUBLISHED

STEP 2 -- Real, on-disk footprint measurement (data_plane.capacity)
Total: 468,201 bytes across 12 files
By extension: {'.json': '5,775b', '.sqlite3': '106,496b', '.ndjson': '253,256b', '.parquet': '72,260b', '.csv': '30,414b'}
Parquet: 72,260 bytes compressed vs. 103,079 bytes as CSV (1.43x smaller)
Partitioning: key='batch', 2 partition(s)

STEP 3 -- Register version 1 (real measured size_bytes/row_counts) and request 5 environments

STEP 4 -- Real capacity plan: naive-if-independent-copies vs. Phase 7's real shared-snapshot cost
Environments requesting this dataset: 5
Distinct physical dataset versions actually stored: 1
Naive total (if each environment had its own copy): 2,341,005 bytes
Actual shared total (Phase 7's real architecture):   468,201 bytes
Savings: 1,872,804 bytes (80.0%)
           dev: cadence=weekly          52.1/yr
   performance: cadence=monthly         12.2/yr
            qa: cadence=weekly          52.1/yr
           sit: cadence=biweekly        26.1/yr
           uat: cadence=release_driven  no fixed cadence

STEP 5 -- Vacuum candidates: an unreferenced, revoked version is identified as reclaimable
Vacuum candidates: 1
  version_number=2 status=revoked reclaimable_bytes=153,844 reason='status=revoked, unreferenced by any environment request'
Version 1 (still referenced by 5 environments) correctly does NOT appear above.

STEP 6 -- Illustrative scenario: Production 100 TB, QA 10%, SIT 5%, UAT 15%, DEV 10%, PERFORMANCE 100%
Naive total (5 independent copies):  140.0 TB
  tier=standard    : shared snapshot = 15.0 TB
  tier=performance : shared snapshot = 100.0 TB
Shared total (Phase 7-style sharing by tier): 115.0 TB
Savings: 25.0 TB (17.9%)
```

Notice `naive_total_storage_bytes` in Step 4 (`2,341,005` bytes) is
exactly `5 x 468,201` -- five environments, each counted as if it owned
an independent copy of the same measured size -- and
`shared_total_storage_bytes` is exactly the one real size on disk. This
is not an estimate; it is the same real `size_bytes` value, summed two
different ways over real, registered `EnvironmentDatasetRequest` rows.

## The API

```
GET  /api/v1/capacity/dataset-versions/{version_id}/footprint
GET  /api/v1/capacity/environment-requests/{request_id}/demand
GET  /api/v1/capacity/plan?dataset_name=...
GET  /api/v1/capacity/vacuum-candidates?dataset_name=...
GET  /api/v1/capacity/illustrative-plan?production_baseline_tb=100
POST /api/v1/capacity/illustrative-plan   (custom IllustrativeCapacityScenario body)
```

The first four read real, already-registered Phase 7 data (nothing is
computed that wasn't already true in the database). The last two are
pure calculations against a configurable scenario — no database access
at all, which is exactly why `GET /illustrative-plan` needs no dataset
to already be registered to answer `ROADMAP.md`'s worked example.

## The core design decision: naive vs. shared is a real comparison, not a hypothetical one

`CapacityPlanner.capacity_plan` never asks "what would a copy cost" as a
guess -- it sums the exact same `DatasetVersion.size_bytes` value once
per environment request (`naive_total_storage_bytes`) and once per
*distinct* version actually referenced (`shared_total_storage_bytes`).
Because every environment in this platform's default example points at
the same certified snapshot, the ratio between the two numbers is always
exactly the number of sharing environments — a mechanical consequence of
Phase 7's architecture, not a claim this phase invents. See
`services/control-plane/tests/test_capacity_planner.py` for the
adversarial case (two environments on *different* versions), where
`storage_savings_bytes` correctly comes out to zero — sharing only saves
storage when environments are actually willing to use the same version.

## What this phase honestly does not measure

`control_plane.domain.capacity.estimator`'s compute-demand figures are a
documented heuristic (`ROWS_PER_COMPUTE_UNIT_HOUR`), not a benchmark --
`ROADMAP.md` Phase 14 (scale/performance engineering) has since happened
and produced real measured per-stage throughput numbers
(`docs/SCALE_AND_PERFORMANCE.md`), but this constant was not touched by
that phase (see `docs/problems/problems_phase_08.md` P8-1 for why no single figure
from it was a direct drop-in replacement). `data_plane.capacity.incremental`
models what an incremental-refresh engine would save; this platform does
not build one. Both are documented explicitly, in their own module
docstrings and in `docs/CAPACITY_COST_TRADEOFFS.md`, as illustrations of
future or unbuilt capability -- never presented as measured fact. See
`docs/problems/problems_phase_08.md` for the complete, honest list of what remains
open after this phase.
