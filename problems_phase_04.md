# Problems — Phase 4 (Production-Scale Data Subsetting)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before implementation began (this initial version), updated as
work proceeded, resolved entries removed once fixed and tested. Anything
left below at the end of the phase is a genuine open issue for a later
phase.

## Risks identified before implementation, and how they were resolved

Written before implementation began, per `CONTRIBUTING.md` step 2; kept
here (rather than deleted) as the record of what was anticipated versus
what actually happened, since every one of these was successfully
resolved and is now verified by a real, passing test:

- **A naive per-table sample produces orphaned child rows** (the entire
  reason this phase exists). Resolved: every strategy only selects an
  anchor Member population; `data_plane.subsetting.closure.build_closure`
  is the single, shared graph walk that pulls the full referential
  closure for that population across all five source systems, so there
  is exactly one referential-integrity implementation to get right, not
  six (one per strategy). See
  `docs/tutorial/04-subsetting-and-referential-closure.md`.
- **Distinguishing an orphan the subsetting engine introduces itself from
  one the Phase 1 estate already had.** Resolved:
  `closure.DanglingReference.category` classifies every dangling
  reference found as `"engine_bug"` (the target id existed in the source
  estate but was not carried into the subset — a real defect) or
  `"source_orphan"` (the target never existed anywhere in the source
  estate — a pre-existing, legitimate Phase 1 edge case). Verified
  end to end against the real generated estate by
  `tests/subsetting/test_closure.py::test_closure_never_introduces_a_new_dangling_reference`,
  which selects every member in the estate (the largest, most
  orphan-exposing closure possible) and asserts zero `engine_bug`
  findings.
- **Some of the estate's own injected orphans can never be reachable from
  a Member-anchored selection at all** (e.g. an orphan `Address` row
  whose `member_id` points at a member that does not exist — the address
  belongs to no one, real or selected, so no selection size can ever
  surface it). This was not obvious until the Phase 1 generator's
  edge-case injection logic (`reference_data/generator.py`) was read
  carefully. Resolved and documented explicitly, with a full
  reachable/unreachable table, in
  `docs/tutorial/04-subsetting-and-referential-closure.md` and
  `data_plane/subsetting/README.md`, rather than left as a silent gap a
  future reader would have to rediscover.
- **Reference/code tables (Provider, Plan, Diagnosis, Procedure,
  Pharmacy) are not owned by any one member** and needed different
  treatment than Member's direct children. Resolved: `closure.py` trims
  each of these to exactly the ids referenced by the selected rows that
  point at them (a Claim's `provider_id`, a ClaimLine's
  `diagnosis_code`, ...), verified by
  `tests/subsetting/test_closure.py::test_closure_provider_table_is_trimmed_to_referenced_providers`
  and the equivalent diagnosis/procedure test.
- **Intentional negative-test orphan injection must never be mistaken for
  an unnoticed bug.** Resolved: a dedicated, explicitly-opt-in module
  (`negative_testing.py`) that only ever runs when a caller asks for it,
  producing findings tagged `category="negative_test_injection"` that
  `validation.py` reports distinctly from both `"engine_bug"` and
  `"source_orphan"` — verified by
  `tests/subsetting/test_negative_testing.py::test_injected_dangling_reference_is_reported_not_hidden`.
- **Reading five heterogeneous on-disk formats back into filterable rows**
  (SQLite, two schema-drifted Parquet claim batches, NDJSON, CSV, and two
  partner feed shapes) without losing the ability to write them back out
  in their original shape. Resolved: `estate_io.py` keeps Parquet claim
  batches and partner-feed files split by their original batch/file
  identity (`ParquetDataset`, `PartnerLabFeedData`), so `writer.py` can
  reproduce the exact same file layout with a subset of rows — verified
  by `tests/subsetting/test_writer.py::test_written_subset_round_trips_through_read_estate`
  and `test_written_subset_is_readable_by_discovery_scanner` (the
  subset estate is provably a real drop-in for the sibling `discovery`
  subpackage, not just superficially similar files).
- **Population size must not be hardcoded to the phase's own "10,000
  members" example**, since the `tiny`/`developer` scale profiles only
  have a few dozen/few hundred members. Resolved: every strategy takes
  its population size/percentage as a runtime parameter; the exact same
  code path demonstrated at `tiny` scale (26 members) is what runs
  unmodified against a `performance`-scale estate (20,000 members) for a
  real 10,000-member subset — see `problems_phase_04.md` P4-3 below for
  what is *not* yet resolved (this hasn't actually been benchmarked at
  that scale).

## Open problems

### P4-1 — Subsetting is not yet wired as a control-plane orchestrated job

- **Status:** open (deliberately deferred; same shape of gap Phase 3
  documented for masking in `problems_phase_03.md` P3-1/`ARCHITECTURE.md`
  section 2.2)
- **Description:** `healthcare_tdm_contracts.JobType.SUBSETTING` and
  `JobRequest.sizing_rule` already exist (Phase 0 scaffolding), but
  nothing submits a `JobRequest` to this package or consumes a
  `JobResult` from it yet — `data_plane.subsetting.cli` is a standalone
  CLI entry point, run directly, exactly like `discovery.cli` and
  `masking.cli` are today. Wiring subsetting as a job the control plane's
  orchestrator submits (translating a `JobRequest.sizing_rule` string
  into a `SubsettingStrategy` + parameters) is `Orchestrator`/`JobType`
  work for a later phase.
- **Repro / detail:** N/A — scope boundary, not a bug.
- **Affected files:** `services/data-plane/src/data_plane/subsetting/cli.py`,
  `libs/contracts/src/healthcare_tdm_contracts/jobs.py`
- **Owner for resolution:** a future job-orchestration phase / control-
  plane work generally. **Correction:** this used to say "Phase 14 (job
  orchestration)" — Phase 14 actually happened, and its scope turned out
  to be scale/performance benchmark tooling (`ROADMAP.md` Phase 14,
  `problems_phase_14.md`), not job-orchestration wiring; that remains
  unscheduled by name.

### P4-2 — No metadata-plane snapshot registry or audit event integration yet

- **Status:** open (deliberately deferred; same shape of gap
  `problems_phase_03.md` documents for masking's snapshot/audit-log edges)
- **Description:** `ARCHITECTURE.md`'s diagram shows `Subsetting ->
  Snapshots` (metadata plane) and an audit-log edge; neither exists yet
  (no snapshot registry database, no audit event log). A subsetting run
  today writes a self-contained `subset_manifest.json`
  (`healthcare_tdm_contracts.SubsetManifest`) next to its output, the
  same interim pattern Phase 3 established with
  `masking_run_summary.json`. `SubsetManifest` is deliberately already
  shaped so a future `SnapshotRecord.source_job_id`-style reference could
  point at a `SubsetManifest.manifest_id` once the registry exists.
- **Repro / detail:** N/A — scope boundary, not a bug.
- **Affected files:** `services/data-plane/src/data_plane/subsetting/manifest.py`,
  `libs/contracts/src/healthcare_tdm_contracts/subsetting.py`
- **Owner for resolution:** The metadata plane's snapshot registry
  (`ROADMAP.md` Phase 7).

### P4-3 — Subsetting at real qa/performance scale has not been benchmarked

- **Status:** resolved (Phase 14) — `data_plane.benchmarks.harness.
  benchmark_pandas_subsetting` ran the real `PERCENTAGE` strategy (this
  same `estate_io.py`/`selection.py`/`closure.py` code path) against a
  real, freshly generated `performance`-scale estate (766,252 rows,
  20,400 members) and measured 8.777s to select 408 members and write
  7,782 claim+claim_line rows, with no memory issues on a 28-core/
  everyday-RAM development machine — see `docs/SCALE_AND_PERFORMANCE.md`
  section 3. This confirms the concrete concern below (acceptable
  runtime/memory behavior at `performance` scale) even though it used
  `PERCENTAGE` rather than the phase's original `fixed_population
  count=10000` example; the underlying code path exercised is identical.
  The original description is kept below for context.
- **Description:** Every strategy is demonstrated end to end against the
  real `tiny` scale profile (26 members) in this phase's tests, and the
  code path is scale-agnostic (nothing hardcodes a population size), but
  the phase's own headline example ("select 10,000 members") has not
  actually been run against the `performance` scale profile (20,000
  members) to confirm acceptable runtime/memory behavior. `estate_io.py`
  reads every dataset fully into memory as plain Python dicts, which is
  the "pandas-compatible local path" this platform's data-plane jobs are
  designed to have (see `ARCHITECTURE.md` section 2.2) but is not the
  Spark-backed path a truly production-scale (multi-million-member) run
  would need.
- **Repro / detail:** `python -m data_plane.reference_data.cli --scale
  performance --out-dir data/tmp/perf-estate` (20,000 members, slow),
  then `python -m data_plane.subsetting.cli --estate-dir
  data/tmp/perf-estate --out-dir data/tmp/perf-subset --strategy
  fixed_population --param count=10000` and measure.
- **Affected files:** `services/data-plane/src/data_plane/subsetting/estate_io.py`
- **Owner for resolution:** Phase 14 (scale and performance engineering,
  PySpark benchmarks) — done; see the Status note above. The
  Spark-backed path for a truly production-scale (multi-million-member)
  run is `data_plane.spark.subsetting_job` (also Phase 14) — it does not
  replace `estate_io.py`'s pandas path (that remains this phase's own
  code), but is the real Spark reimplementation the description above
  anticipated needing eventually.

### P4-4 — The relationship graph is hand-authored, not derived from the catalog

- **Status:** open (documented limitation, not a defect)
- **Description:** `closure.py`'s graph of which column references which
  entity (`Coverage.plan_id -> Plan`, `Claim.provider_id -> Provider`,
  ...) is hand-written Python, mirroring how `reference_data/generator.py`
  actually built the estate. It does not read relationship metadata from
  the Phase 2 catalog (which does not record foreign-key relationships
  today, only per-column classification) or infer them from the data. A
  new source system or a new relationship requires a code change to
  `build_closure`, not a configuration change.
- **Repro / detail:** N/A — architectural limitation, consistent with
  this phase's own scope (implement the six required strategies against
  the known Phase 1 relationships, not a generic schema-inference engine).
- **Affected files:** `services/data-plane/src/data_plane/subsetting/closure.py`
- **Owner for resolution:** Not currently scheduled by name in
  `ROADMAP.md`; a future phase extending the catalog to carry FK/
  relationship metadata could make this data-driven.

### P4-5 — A dataset with zero selected rows is written as a missing file/table, not an empty one

- **Status:** open (documented limitation, not a defect)
- **Description:** `writer.py` skips writing a table/file entirely when
  its selected row list is empty (e.g. a subset with no partner-feed v1
  records at all writes no `v1_legacy_flat_file` directory), rather than
  writing an empty-but-schema-correct artifact. This mirrors how the
  original Phase 1 writers already behave for an empty claims batch, but
  means a downstream consumer of a subset must tolerate a missing
  table/file for any of the fourteen entities, not assume all of them are
  always present.
- **Repro / detail:** Subset a `tiny` estate down to 1-2 members with
  `fixed_population` and inspect the output directory — some of the
  fourteen datasets will have no file at all if that member had zero rows
  in them.
- **Affected files:** `services/data-plane/src/data_plane/subsetting/writer.py`
- **Owner for resolution:** Acceptable as-is for a teaching-grade
  implementation; revisit if a later phase's consumer needs a stronger
  "always all fourteen tables/files exist" guarantee.

### P4-6 — Negative-test injection supports only one relationship today

- **Status:** open (documented limitation, not a defect)
- **Description:** `negative_testing.inject_negative_test_orphan` only
  knows how to break `claim.provider_id`
  (`negative_testing.SUPPORTED_RELATIONSHIPS`). Extending it to other
  relationships (e.g. deliberately orphaning a `ClaimLine.diagnosis_code`)
  is a small, mechanical addition following the same pattern, but was not
  needed to satisfy this phase's requirement ("prevent dangling
  relationships unless intentionally injected for negative testing" —
  demonstrating the mechanism once, correctly, was the bar).
- **Repro / detail:** `inject_negative_test_orphan(closure,
  relationship="claim_line.diagnosis_code")` raises `ValueError` today.
- **Affected files:** `services/data-plane/src/data_plane/subsetting/negative_testing.py`
- **Owner for resolution:** Extend on demand; not scheduled by name.

### P4-7 — `risk_edge_case`'s signal detectors are keyed to Phase 1's exact injected sentinel values

- **Status:** open (documented limitation, not a defect)
- **Description:** `selection.select_risk_edge_case` looks for the exact
  literal values `reference_data/generator.py` injects for its edge cases
  (`"SYN-PRV-99999"`, `"SYN-PRV-99998"`, `"SYN-Z99.9-UNMAPPED"`,
  `{"TBD", "UNKNOWN", ""}`, ...). If a future phase changes those
  sentinel values, this strategy's signal detectors need updating to
  match — they are not derived from `edge_cases.EdgeCaseReport`
  automatically (that report exists only in-memory during generation and
  is not persisted to the written estate today).
- **Repro / detail:** N/A — coupling is deliberate and documented (see
  module docstring), not accidental.
- **Affected files:** `services/data-plane/src/data_plane/subsetting/selection.py`,
  `services/data-plane/src/data_plane/reference_data/generator.py`
- **Owner for resolution:** Low priority; revisit only if the generator's
  sentinel values change.
