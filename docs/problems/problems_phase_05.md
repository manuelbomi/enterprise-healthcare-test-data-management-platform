# Problems — Phase 5 (Synthetic Test Data Generation)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process.
Risks identified before/during implementation and how they were
resolved are kept here as the record of what was anticipated versus what
actually happened; anything left below at the end of the phase is a
genuine open issue for a later phase.

## Risks identified during implementation, and how they were resolved

- **Confusing this phase with Phase 1's `reference_data` package**, which
  also "generates synthetic data." Resolved by making the distinction
  explicit and load-bearing everywhere a reader would look for it: the
  `data_plane.synthetic` package docstring, this phase's tutorial
  chapter's second section, and `ARCHITECTURE.md`'s own pipeline diagram
  (`... -> MASK -> GENERATE OPTIONAL SYNTHETIC DATA -> ...`) all say the
  same thing the same way — Phase 1 builds an entire estate from nothing;
  this phase only ever augments/supplements an existing (ideally already
  masked/subsetted) dataset, one pipeline stage later.
- **A synthetic or negative-test record could be silently mistaken for a
  masked-real one once merged into the same files/tables.** This was the
  phase's own named requirement ("never allow synthetic records to be
  mistaken for real records"), so it was resolved with two independent,
  redundant mechanisms rather than one: (1) a `data_provenance` column
  added to *every* row this phase writes, including retagging every
  pre-existing base-estate row `MASKED_PRODUCTION_LIKE` in an "augment"
  run (`provenance.py`), and (2) a scenario-sub-range ID convention
  (`SYN-<ENTITY>-SCEN-<seq>`, `ids.py`) that cannot collide with Phase
  1's `SYN-<ENTITY>-<seq>` IDs by construction. Verified end to end
  against real generated/subsetted data by
  `tests/synthetic/test_synthetic_engine_against_real_estate.py::test_synthetic_scenario_ids_never_collide_with_base_estate_ids`
  and `test_augmented_output_is_readable_back_by_estate_io`, and
  demonstrated with real output in
  `docs/tutorial/05-synthetic-scenario-generation.md`.
- **Heterogeneous provenance-column key sets across merged rows broke one
  of Phase 4's five reused writers.** Discovered by actually running the
  CLI against real data (not just unit tests of individual generators):
  `data_plane.subsetting.writer.write_pbm_extract` derives its CSV header
  from `rows[0].keys()` alone, so once a Prescription list mixed rows
  with and without a `scenario_type` key, `csv.DictWriter` raised
  "dict contains fields not in fieldnames." Resolved by normalizing every
  entity's row list to a uniform key set (missing keys backfilled `None`)
  immediately before handing rows to the (unmodified, reused) writer —
  see `normalize.py`'s module docstring for the full explanation of why
  only that one writer needed this and the other four tolerate
  heterogeneous keys natively. Covered by `tests/synthetic/test_normalize.py`
  and proven against the real writer by
  `tests/synthetic/test_synthetic_engine_against_real_estate.py::test_augment_mode_merges_scenarios_into_the_base_estate`.
- **The partner lab feed's legacy v1 pipe-delimited format writes only
  the columns in a fixed `fieldnames` list captured at read time, not
  whatever keys a row dict happens to have** — so tagging a v1 row with
  `data_provenance` would have been silently dropped on write if
  `fieldnames` itself weren't also updated. Resolved:
  `tag_base_estate_as_masked_production_like` extends the stored
  `fieldnames` tuple alongside tagging the rows themselves. Covered by
  `tests/synthetic/test_provenance.py::test_tag_base_estate_marks_every_entity_masked_production_like`.
- **A naive "top up a missing reference-table entity" fallback risked
  discarding (or duplicating) a base estate's perfectly good reference
  data for entities that weren't actually missing.** Caught by writing
  `tests/synthetic/test_reference_pool.py::test_engine_tops_up_only_the_missing_entity_not_the_whole_pool`
  *before* trusting the first implementation: a base estate with real
  Plans but zero Providers ended up with a duplicate, fabricated Plan too
  (`build_minimal_reference_pool` always generated and appended all five
  reference entities, not just the missing one). Resolved by adding an
  `only` parameter restricting which entities `build_minimal_reference_pool`
  actually generates, and having `engine.py` compute the precise missing
  set rather than treating "any gap" as "regenerate everything."

## Open problems

### P5-1 — Scenario parameters are hand-authored, not learned from real distribution statistics

- **Status:** open (documented limitation, not a defect)
- **Description:** Cost thresholds (`HIGH_COST_MIN`/`HIGH_COST_MAX`),
  drug-interaction-risk pairs, the exact boundary-date set, and every
  other scenario-shaping constant in `scenarios.py` are hand-authored
  Python, not derived from real (masked, aggregate) distribution
  statistics the metadata plane might one day hold. This matches the
  phase's own scope (implement the eleven required scenarios correctly,
  not a general statistical scenario-inference engine) but means a
  future user cannot, for example, ask for "high cost" to mean "above the
  99th percentile of this specific dataset's actual claim distribution"
  without a code change.
- **Repro / detail:** N/A — architectural limitation, consistent with
  scope.
- **Affected files:** `services/data-plane/src/data_plane/synthetic/scenarios.py`
- **Owner for resolution:** Not currently scheduled by name in
  `ROADMAP.md`; a natural fit once the metadata plane holds real
  aggregate statistics to learn from.

### P5-2 — Only `count` is exposed as a CLI-tunable scenario parameter

- **Status:** open (documented limitation, not a defect)
- **Description:** `data_plane.synthetic.cli`'s `--count SCENARIO=N`
  flag tunes how many instances of a scenario are generated, but a
  scenario's other parameters (e.g. `very_large_claim_histories`'s
  `claims_per_member`, currently fixed at 250 regardless of `count`) are
  only reachable through the Python API
  (`generate_very_large_claim_histories(ctx, count=1, claims_per_member=500)`),
  not the CLI.
- **Repro / detail:** `python -m data_plane.synthetic.cli --out-dir out
  --scenario very_large_claim_histories --count
  very_large_claim_histories=3` controls how many *members* get a large
  history, not how large each history is.
- **Affected files:** `services/data-plane/src/data_plane/synthetic/cli.py`,
  `services/data-plane/src/data_plane/synthetic/scenarios.py`
- **Owner for resolution:** Low priority; extend the CLI's parameter
  surface on demand.

### P5-3 — Not yet wired as a control-plane orchestrated job or a metadata-plane snapshot

- **Status:** open (deliberately deferred; same shape of gap Phases 3
  and 4 documented for their own outputs)
- **Description:** `healthcare_tdm_contracts.JobType.SYNTHETIC_GENERATION`
  already exists (Phase 0 scaffolding), but nothing submits a
  `JobRequest` to this package or consumes a `JobResult` from it yet —
  `data_plane.synthetic.cli` is a standalone CLI entry point, exactly
  like `discovery.cli`, `masking.cli`, and `subsetting.cli` are today.
  Likewise, no metadata-plane snapshot registry exists yet to record a
  `SyntheticGenerationManifest` against
  (`ARCHITECTURE.md`'s `Synthetic -> Snapshots` edge).
- **Repro / detail:** N/A — scope boundary, not a bug.
- **Affected files:** `services/data-plane/src/data_plane/synthetic/cli.py`,
  `libs/contracts/src/healthcare_tdm_contracts/jobs.py`,
  `libs/contracts/src/healthcare_tdm_contracts/synthetic.py`
- **Owner for resolution:** a future job-orchestration phase / the
  metadata plane's snapshot registry (`ROADMAP.md` Phase 7), same as
  `docs/problems/problems_phase_04.md` P4-1/P4-2. **Correction:** this used to say
  "Phase 14 (job orchestration)" — Phase 14 actually happened and its
  scope was scale/performance benchmark tooling, not job-orchestration
  wiring; that remains unscheduled by name (see `docs/problems/problems_phase_14.md`).

### P5-4 — No scenario generates a new Address row

- **Status:** open (documented limitation, not a defect)
- **Description:** `merge.py` supports merging an `address` entity from
  a `ScenarioBatch` (it's in `_LIST_FIELD_BY_ENTITY`), but none of the
  eleven required scenario generators actually produces one — every
  scenario-generated Member in this phase's output relies on the base
  estate having no Address requirement (Address is optional context, not
  a hard dependency of any of the eleven scenarios as specified).
- **Repro / detail:** N/A — no scenario in the required list needs an
  Address; the merge path is simply unexercised, not broken (covered
  structurally by `tests/synthetic/test_merge.py::test_merge_appends_plain_list_entities`
  using a hand-built `address` batch).
- **Affected files:** `services/data-plane/src/data_plane/synthetic/scenarios.py`
- **Owner for resolution:** Extend on demand if a future scenario needs
  it (e.g. a "member moved without an address update" scenario).

### P5-5 — Provenance columns added to the SQLite/PostgreSQL-stand-in tables are a modeling simplification

- **Status:** open (documented limitation, not a defect)
- **Description:** `data_provenance`/`scenario_type`/`synthetic_batch_id`
  are added as ordinary columns to every entity this phase writes,
  including the six entities materialized into the SQLite enrollment
  stand-in (Member, MemberDemographics, Address, Plan, Coverage,
  Provider). A real production PostgreSQL enrollment schema would need
  an explicit migration to add these columns; this repository's SQLite
  stand-in has no fixed schema (each write recreates the table from
  whatever columns the DataFrame has, see `reference_data/README.md`'s
  "Why Postgres data has no malformed values" for the same kind of
  simplification already made in Phase 1), so this was not a blocker
  here, but a real deployment's enrollment OLTP system would need this
  column added deliberately, not incidentally.
- **Repro / detail:** N/A — consistent with how this repository already
  treats its SQLite stand-in elsewhere.
- **Affected files:** `services/data-plane/src/data_plane/synthetic/provenance.py`,
  `services/data-plane/src/data_plane/reference_data/postgres_models.py`
- **Owner for resolution:** Not currently scheduled; relevant only if
  this platform ever targets a real (non-stand-in) enrollment database.

### P5-6 — `very_large_claim_histories` at its default size has not been benchmarked at real scale

- **Status:** open (documented limitation, not a defect; same shape of
  gap as `docs/problems/problems_phase_04.md` P4-3)
- **Description:** The default 250-claims-per-member volume is
  demonstrated end to end against a real `tiny`-scale base estate in this
  phase's tests and tutorial (contributing 250-629 of the ~296-460 total
  claim/claim_line rows in the worked example), but has not been run
  against a `qa`/`performance`-scale base estate, or at a much larger
  `claims_per_member` value, to confirm acceptable runtime/memory
  behavior — the same "pandas-compatible local path, not yet the
  Spark-backed production path" caveat Phase 4 already documents applies
  identically here, since this phase reuses Phase 4's `estate_io.py`/
  `writer.py` in full.
- **Repro / detail:** Generate a `performance`-scale base estate, subset
  it, then run
  `python -m data_plane.synthetic.cli --base-estate-dir <perf-subset>
  --out-dir <out> --scenario very_large_claim_histories --count
  very_large_claim_histories=5` and measure.
- **Affected files:** `services/data-plane/src/data_plane/synthetic/scenarios.py`,
  `services/data-plane/src/data_plane/synthetic/engine.py`
- **Owner for resolution:** Phase 14 (scale and performance engineering)
  happened, but its benchmark suite
  (`data_plane.benchmarks`/`docs/SCALE_AND_PERFORMANCE.md`) covers
  dataset generation, masking, subsetting, and validation throughput —
  it does not exercise `data_plane.synthetic` at all. This item remains
  genuinely open; not currently scheduled by name.
