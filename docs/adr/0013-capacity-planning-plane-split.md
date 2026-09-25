# ADR-0013: Split capacity planning across planes -- real measurement in the data plane, real aggregation/modeling in the control plane

## Status

Accepted

## Context

`ROADMAP.md` Phase 8 asks for two genuinely different kinds of work:

1. **Real footprint measurement** -- actual on-disk bytes, actual
   Parquet-vs-CSV compression ratios, actual Hive-style partition
   layout. This only means anything against real files on disk (an
   estate `data_plane.reference_data` generated, a certification
   pipeline's `final/` output, ...).
2. **Real capacity planning/aggregation** -- given Phase 7's real,
   already-registered `DatasetVersion`/`EnvironmentDatasetRequest` rows,
   compute naive-vs-shared storage totals, per-environment compute
   demand, and vacuum candidates. This only means anything against the
   metadata plane's database (`services/control-plane/src/control_plane/db`),
   the system of record Phase 7 built.

Putting both in one module would mean either the data plane importing
`control_plane`'s database session (a plane-separation violation --
ADR-0003 says a plane may only be reached through its published
interface), or the control plane reaching directly into object storage
to re-measure files (which `problems_phase_07.md` P7-8 already
identifies as a real, currently-unclosed gap requiring a storage
adapter that does not exist yet -- `problems_master.md` P0-3).

## Decision

Split capacity planning across two new, additive modules, following the
exact precedent every phase since Phase 3 has already established for
data-plane-vs-control-plane work:

- `services/data-plane/src/data_plane/capacity/` -- real, on-disk
  measurement only. Operates on filesystem paths, exactly like
  `data_plane.discovery`, `data_plane.subsetting`,
  `data_plane.certification` before it. Never imports `control_plane`.
- `services/control-plane/src/control_plane/domain/capacity/` -- real
  aggregation over the Phase 7 lifecycle database (via the existing,
  untouched `LifecycleRepository`), plus a pure, configurable
  illustrative percentage-of-production scenario model that needs
  neither disk access nor a database. Never imports `data_plane`.

The two are joined only by a standalone operator script,
`scripts/demo_phase8_capacity.py`, the same shape
`scripts/demo_phase7_lifecycle.py` already uses to glue a real
certification pipeline run (data plane) to the real lifecycle API
(control plane) -- neither service's own installed package imports the
other anywhere.

Both sides share their result *shapes*, not their code:
`healthcare_tdm_contracts.capacity` defines `CompressionMeasurement`,
`FootprintMeasurementReport`, and `PartitionSummary` (produced by the
data-plane side) alongside `DatasetVersionFootprint`,
`EnvironmentCapacityDemand`, `CapacityPlan`, `VacuumCandidate`,
`EnvironmentCapacityRequirement`, `IllustrativeCapacityScenario`, and
`IllustrativeCapacityPlan` (produced by the control-plane side) -- the
same "typed contract, no business logic" rule every other
`healthcare_tdm_contracts` module follows.

## Consequences

- Real Parquet compression measurement (`data_plane.capacity.footprint`)
  can be exercised, and tested, against real Phase 1/6 output completely
  independently of any running control-plane process or database --
  exactly how `data_plane.certification`'s own tests already work.
- `CapacityPlanner` (`control_plane.domain.capacity`) can be exercised,
  and tested, against a real SQLite-backed `LifecycleRepository`
  completely independently of any real files on disk -- it consumes
  `DatasetVersion.size_bytes`/`row_counts` exactly as Phase 7 already
  registers them, never re-measuring them itself. This means
  `problems_phase_07.md` P7-8 ("the control plane trusts caller-supplied
  `size_bytes`") is *not* closed by this ADR -- see
  `problems_phase_08.md` P8-2 for the honest continuation of that gap
  and why closing it fully needs a real storage adapter (P0-3), not just
  a capacity-planning phase.
- A caller that wants the two joined together (real measurement feeding
  a real registration, which then feeds real planning) writes the same
  kind of standalone glue script Phase 7 already established the
  pattern for, rather than either service importing the other.
