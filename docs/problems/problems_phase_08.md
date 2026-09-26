# Problems — Phase 8 (Storage and Compute Footprint Management)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before implementation began (this initial version), updated as
work proceeded, resolved entries removed once fixed and tested. Anything
left below at the end of the phase is a genuine open issue for a later
phase.

## Risks identified before implementation, and how they were resolved

- **Phase 7 already solved "avoid unnecessary duplicate physical
  copies" architecturally (`EnvironmentDatasetRequest` references a
  `DatasetVersion` by foreign key, never copies `storage_uri`). This
  phase must not re-solve that — it must build the capacity/cost
  *modeling* layer on top of it, and use it to make the savings
  concrete and quantifiable.** Resolved: `CapacityPlanner.capacity_plan`
  (`control_plane/domain/capacity/planner.py`) reads real
  `EnvironmentDatasetRequest`/`DatasetVersion` rows via the existing,
  untouched `LifecycleRepository` and computes two real numbers from
  them — `naive_total_storage_bytes` (what it would cost if every
  environment request owned an independent physical copy of its
  dataset version's measured size) vs. `shared_total_storage_bytes`
  (the sum over only the *distinct* `DatasetVersion`s actually
  referenced) — both derived from real, DB-backed Phase 7 data, not
  fabricated. `LifecycleRepository`/`control_plane/db/models.py` are
  not modified by this phase.
- **Plane separation (ADR-0003) needed to stay real: "real Parquet
  compression measurement" is data-plane territory (it reads actual
  files off disk), but "capacity plan across registered dataset
  versions/environment requests" is control-plane territory (it reads
  the Phase 7 metadata-plane database) — mixing them in one module
  would blur the boundary Phase 3-7 have consistently respected.**
  Resolved with a new ADR
  (`docs/adr/0013-capacity-planning-plane-split.md`): real footprint
  *measurement* (on-disk bytes, Parquet-vs-CSV compression ratios,
  partition layout) lives in `services/data-plane/src/data_plane/capacity/`
  and operates only on paths on disk, exactly like
  `data_plane.certification`/`data_plane.subsetting` before it; capacity
  *planning* (aggregating already-registered `size_bytes`/`row_counts`
  across dataset versions and environment requests, computing
  naive-vs-shared storage, computing illustrative percentage-of-production
  scenarios) lives in `services/control-plane/src/control_plane/domain/capacity/`
  and never imports `data_plane`, mirroring the exact split
  `scripts/demo_phase7_lifecycle.py` already established between the two
  services. `scripts/demo_phase8_capacity.py` is the one place, outside
  either service's installed package, that imports both — the same
  pattern Phase 7's demo script uses.
- **`ROADMAP.md`'s "Production: 100 TB, QA 10%, SIT 5%, UAT 15%" example
  needed a real, configurable model, not a one-off hardcoded
  calculation, and needed an honest answer for the two environments the
  example doesn't mention (DEV, PERFORMANCE).** Resolved:
  `EnvironmentCapacityRequirement` (`libs/contracts`) is a real,
  general-purpose per-environment target-percentage-of-production
  config shape, with `DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS` seeding
  all five example environments (DEV 10%, QA 10%, SIT 5%, UAT 15%,
  PERFORMANCE 100%) — PERFORMANCE is deliberately modeled at 100% and in
  its own `share_tier` ("performance" vs "standard"), with the rationale
  documented in the model itself and in
  `docs/CAPACITY_COST_TRADEOFFS.md`: subsetting a performance-test
  environment defeats the purpose of the test it's meant to run, so its
  cost is real, not wasteful, and it cannot honestly share a snapshot
  sized for the other four. `illustrative_capacity_plan` computes both
  the naive (every environment its own copy) and shared-by-tier
  (`share_tier`, mirroring the real Phase 7 mechanism where multiple
  environments requesting the same `dataset_name` share one
  `DatasetVersion`) totals, clearly labeled as an illustrative, scaled
  model (see its docstring and `docs/CAPACITY_COST_TRADEOFFS.md`), never
  presented as a measurement.
- **Real compression numbers needed to come from real Phase 1/6 output,
  not be invented.** Resolved: `data_plane.capacity.footprint.measure_parquet_compression`
  reads an actual `.parquet` file written by
  `data_plane.reference_data.writers.parquet_writer` (or any other
  pandas-written Parquet file in the estate), re-encodes the *same*
  in-memory rows as CSV, and reports the real compressed (on-disk
  Parquet) vs. re-encoded-CSV byte counts and their ratio — see the
  Phase 8 report for the actual measured numbers from a real generated
  `tiny`-scale estate. The CSV re-encoding is an honestly documented
  proxy for "uncompressed, row-oriented" size (not a bit-for-bit
  decompressed Parquet byte count, which pandas/pyarrow does not expose
  directly) — the module docstring says this explicitly.
- **"Incremental refresh" and "copy-on-write" needed to be demonstrated
  without fabricating an incremental-refresh engine that does not
  exist.** Resolved honestly: `data_plane.capacity.incremental.estimate_incremental_savings`
  is a real function that computes a real delta between two already-registered
  dataset versions' row counts (real arithmetic on real data) and reports
  what a true incremental refresh *would* have saved relative to the full
  reprocessing Phase 7's `refresh()` actually performs today — it is
  explicitly documented, in its own docstring and in
  `docs/CAPACITY_COST_TRADEOFFS.md`, as a modeled illustration of an
  unbuilt capability, not a claim that incremental refresh exists.
  Copy-on-write and vacuum/cleanup are documented as *concept mappings*
  onto mechanisms Phase 7 already built for real (a refresh
  atomically repoints `EnvironmentDatasetRequest.current_version_id`
  to a new immutable `DatasetVersion` without mutating the old one —
  copy-on-write at the metadata-pointer level; `apply_retention` plus
  this phase's new, real `CapacityPlanner.vacuum_candidates` — expired/
  revoked/rolled-back versions with zero referencing environment
  requests — is the "what is safe to vacuum" query a cleanup job would
  run) rather than as new infrastructure, per the operational
  instruction to avoid "speculative infrastructure that doesn't exist
  yet."

## Open problems

### P8-1 — Compute-demand and processing-volume figures are heuristic, not benchmarked

- **Status:** open (documented limitation, not a defect)
- **Description:** `control_plane.domain.capacity.estimator` turns a
  dataset version's row counts and an environment's refresh cadence into
  an "estimated compute-unit-hours" and "estimated annual processing
  volume" figure using a single hardcoded throughput constant
  (`ROWS_PER_COMPUTE_UNIT_HOUR`), not a measured Spark benchmark. This is
  the same honest gap `docs/problems/problems_phase_06.md` documents for masking's
  distribution-shape checking: a plausible, clearly-labeled placeholder,
  not a production SLA.
- **Repro / detail:** N/A — read `estimator.py`'s module docstring; the
  constant is a documented assumption, not derived from any real job
  run in this repository.
- **Affected files:** `services/control-plane/src/control_plane/domain/capacity/estimator.py`
- **Owner for resolution:** `ROADMAP.md` Phase 14 (scale and performance
  engineering, PySpark benchmarks) happened and now provides real
  measured per-stage throughput figures (dataset generation ~24,500-
  24,900 rows/sec, pandas masking ~2,300-2,700 rows/sec, Spark masking
  ~1,700-12,700 rows/sec depending on scale, pandas/Spark subsetting
  ~265-2,560 rows/sec — see `docs/SCALE_AND_PERFORMANCE.md`), but this
  control-plane constant was not touched (control-plane changes were
  out of Phase 14's scope) and none of those figures is a single
  "subset+mask+certify pipeline" number this estimator could drop in
  directly. Replacing `ROWS_PER_COMPUTE_UNIT_HOUR` with one of Phase 14's
  real figures (or a real end-to-end pipeline benchmark) remains a
  genuinely open follow-up for whichever phase next touches
  `control_plane.domain.capacity`.

### P8-2 — `CapacityPlanner` still trusts `DatasetVersion.size_bytes`/`row_counts` as registered (does not re-measure them itself)

- **Status:** open (documented limitation, not a defect; direct
  continuation of `docs/problems/problems_phase_07.md` P7-8)
- **Description:** P7-8 already documents that `register_dataset_version`
  trusts caller-supplied `size_bytes`/`row_counts` rather than
  independently re-deriving them, and names this exact phase
  ("Phase 8: storage/compute footprint management") as the phase with
  the tooling to close that gap. This phase *does* deliver real,
  independent measurement tooling
  (`data_plane.capacity.footprint.measure_directory_footprint`), and
  `scripts/demo_phase8_capacity.py` demonstrates using it to compute the
  `size_bytes` a registration call passes — but `LifecycleRepository.register_dataset_version`
  itself (untouched by this phase, per the plane-separation decision
  above) still accepts whatever the caller passes without calling into
  `data_plane` to verify it, because the control plane has no direct
  object-storage read access (ADR-0005/0003) and adding one would be a
  bigger architectural change than this phase's scope. The gap is
  narrower after this phase (real tooling now exists for a registration
  pipeline to use) but not closed at the control-plane trust boundary.
- **Repro / detail:** Register a dataset version via
  `POST /api/v1/lifecycle/dataset-versions` with a `size_bytes` that
  does not match `storage_uri`'s actual on-disk size; no validation
  rejects the mismatch, exactly as P7-8 already documents.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`,
  `services/data-plane/src/data_plane/capacity/footprint.py`
- **Owner for resolution:** Same as P7-8 — would require either a
  control-plane-side storage adapter (ADR-0005's interface, not yet
  implemented per `docs/problems/problems_master.md` P0-3) or a future job-
  orchestration step (per `docs/problems/problems_phase_07.md` P7-7, whose own text
  has been corrected: this is not Phase 14, which turned out to be
  scale/performance benchmark tooling) that runs the data-plane
  measurement and passes its output to registration, rather than a
  human/script doing so by convention.

### P8-3 — No automatic vacuum/deletion job; `vacuum_candidates` is read-only

- **Status:** open (documented scope boundary, not a defect)
- **Description:** `CapacityPlanner.vacuum_candidates` (and
  `GET /api/v1/capacity/vacuum-candidates`) correctly *identifies*
  dataset versions that are safe to physically delete (status
  EXPIRED/REVOKED/ROLLED_BACK and referenced by zero
  `EnvironmentDatasetRequest`s), but nothing in this phase actually
  deletes the underlying `storage_uri` — this repository does not
  implement real object-storage deletion (no storage adapter exists
  yet, `docs/problems/problems_master.md` P0-3), and even if one did, physically
  deleting data on a read-only "here's what's reclaimable" endpoint's
  say-so without a human/CI approval step would be a dangerous
  default. This mirrors `docs/problems/problems_phase_07.md` P7-3's "apply_retention
  has no automatic trigger" gap for the same underlying reason.
- **Repro / detail:** Call `GET /api/v1/capacity/vacuum-candidates`
  after revoking a dataset version no environment references; observe
  the version still exists (as it should) and no deletion occurs.
- **Affected files:** `services/control-plane/src/control_plane/domain/capacity/planner.py`,
  `services/control-plane/src/control_plane/api/v1/capacity.py`
- **Owner for resolution:** Same owner note as P7-3/P7-2 — a future
  scheduler-deployment phase, once a real storage adapter exists
  (P0-3).

### P8-4 — Illustrative capacity scenarios are not persisted or versioned

- **Status:** open (documented scope boundary, not a defect)
- **Description:** `POST /api/v1/capacity/illustrative-plan` is a pure,
  stateless calculation (no database write) — a caller cannot save a
  named scenario ("2027 budget planning run") and retrieve it later. A
  real capacity-planning tool would let a capacity planner persist and
  compare scenarios over time.
- **Repro / detail:** N/A — feature gap, not incorrect behavior.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/capacity.py`
- **Owner for resolution:** Not currently scheduled by name; a natural
  UI-driven feature for Phase 9 (the web console) once there is a
  screen to drive it from.

## Resolved problems

_(None yet — this is the initial version of this file, written before
implementation. This section will list problems that were opened and
then resolved during this phase, kept briefly for history before being
pruned per `CONTRIBUTING.md` step 6, if any are found and fixed before
the phase is considered done.)_
