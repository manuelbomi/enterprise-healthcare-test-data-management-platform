# Storage and compute capacity: honest cost-vs-realism tradeoffs

This document is required reading before treating any number Phase 8
(`services/control-plane/src/control_plane/domain/capacity`,
`services/data-plane/src/data_plane/capacity`) produces as more precise
or more universal than it actually is. It follows the same honest tone
`docs/CERTIFICATION_VS_MASKING.md` and
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` already set for this
repository: overclaiming precision is worse than being explicit about
what is measured, what is modeled, and what is illustrative.

Every number below comes from a real run of
`scripts/demo_phase8_capacity.py` against a real, generated `developer`-
scale estate, a real Phase 6 certification pipeline run, and a real
Phase 7 lifecycle database (SQLite) -- nothing here is invented.

## 1. Real measurement vs. modeled illustration -- which is which

| Number | Real or modeled? | Source |
|---|---|---|
| On-disk bytes of a directory (`FootprintMeasurementReport.total_bytes`) | **Real** -- `Path.stat().st_size`, summed | `data_plane.capacity.footprint.measure_directory_footprint` |
| Parquet compressed size (`CompressionMeasurement.compressed_bytes`) | **Real** -- actual file size on disk | same |
| "Uncompressed" comparison size (`CompressionMeasurement.uncompressed_estimate_bytes`) | **Real bytes, honestly-scoped proxy** -- the same rows re-encoded as CSV in memory, not a bit-for-bit "Parquet with compression off" byte count | same |
| Row counts, retention days, `referenced_by_environments` | **Real** -- read directly from Phase 7's registered `DatasetVersion`/`EnvironmentDatasetRequest` rows | `control_plane.domain.capacity.planner.CapacityPlanner` |
| Naive-vs-shared storage totals (`CapacityPlan.naive_total_storage_bytes` / `shared_total_storage_bytes`) | **Real** -- real `size_bytes` values, summed two different ways over real registered rows | same |
| Vacuum candidates | **Real** -- a live query over real, current version status and reference counts | same |
| Compute-unit-hours / annual processing volume | **Modeled** -- real row counts and real cadence data, multiplied by a documented, unbenchmarked throughput constant | `control_plane.domain.capacity.estimator` |
| Incremental-refresh savings | **Modeled** -- real row-count deltas between two real dataset versions, describing what an incremental-refresh engine *would* save if this platform built one (it does not) | `data_plane.capacity.incremental` |
| "Production: 100 TB, QA 10%, ..." scenario | **Illustrative** -- a configurable hypothetical, not measured from anything | `control_plane.domain.capacity.planner.illustrative_capacity_plan` |

If a number in this platform's API responses or reports doesn't say
which of these it is, that is a documentation gap -- every capacity
contract in `healthcare_tdm_contracts.capacity` documents which kind it
is in its own docstring.

## 2. Real measured numbers, and what they actually show

A real run of `scripts/demo_phase8_capacity.py` (developer-scale estate,
40% member subset, real masking + certification) measured:

```
Total: 468,201 bytes across 12 files
By extension: .json=5,775b  .sqlite3=106,496b  .ndjson=253,256b  .parquet=72,260b  .csv=30,414b
Parquet: 72,260 bytes compressed vs. 103,079 bytes as CSV (1.43x smaller)
```

**This is a genuinely real, if scale-dependent, finding, not a
fabricated "Parquet is always better" claim.** Measuring the *same*
generator's `tiny` scale profile (a handful of rows per file) instead
shows Parquet **losing** to CSV -- an overall ratio of about **0.52x**
(Parquet larger than the CSV re-encoding of the same rows), because
Parquet's per-file footer and per-column-chunk statistics are a fixed
overhead that a 4-92 row file cannot amortize. The same measurement
against the `qa` scale profile (thousands of rows per file) shows a
clearly favorable overall ratio of about **3.7x**. All three numbers are
real measurements of the same code path
(`data_plane.capacity.footprint.measure_parquet_compression`) at
different, real row counts -- see
`services/data-plane/tests/capacity/test_footprint.py`, which asserts
the `tiny`-scale ratio only for internal consistency (never `>= 1.0`,
because that would be asserting a specific real measurement always comes
out a particular way) and separately asserts the `developer`-scale ratio
is `> 1.0`.

**The honest takeaway:** Parquet's compression/columnar-encoding
advantage is real, but it is not a fixed multiplier -- it is a property
of the data's actual scale and structure. A capacity plan built from
`tiny`-scale measurements would *understate* production storage needs;
this platform's own certification pipeline defaults to `tiny` scale for
fast local iteration (`data_plane.certification.pipeline`'s
`scale="tiny"` default), which is exactly why `CapacityPlanner` never
hardcodes a compression assumption -- it only ever reports real,
already-measured `size_bytes`, whatever scale produced them.

## 3. Naive-vs-shared: the real, quantified answer to "does sharing actually save anything"

The same demo run, after requesting the same dataset version into all
five example environments:

```
Environments requesting this dataset: 5
Distinct physical dataset versions actually stored: 1
Naive total (if each environment had its own copy): 2,341,005 bytes
Actual shared total (Phase 7's real architecture):   468,201 bytes
Savings: 1,872,804 bytes (80.0%)
```

This is not an estimate -- it is `5 x 468,201` (what independent copies
would cost) vs. `1 x 468,201` (what Phase 7's `EnvironmentDatasetRequest`
-> `DatasetVersion` foreign-key architecture actually costs), computed
from real registered rows. The percentage savings scales with the number
of sharing environments, not with dataset size -- at 5 environments
sharing one version, the naive-vs-shared ratio is always 5:1 (80%
savings) regardless of whether the dataset is 468 KB or 468 GB. **The
one caveat:** this number assumes every sharing environment is genuinely
willing to use the *same* dataset version. An environment with a real
requirement for a different subset percentage, a different masking
policy, or a different refresh timing cannot share -- see section 4.

## 4. Why the illustrative "100 TB" scenario isn't just "share everything"

`ROADMAP.md`'s worked example (`Production: 100 TB, QA 10%, SIT 5%, UAT
15%`) is deliberately not modeled as "one snapshot shared by everyone" --
that would trivially "save" the most but would be dishonest for one
environment: **PERFORMANCE**.

`healthcare_tdm_contracts.DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS`
models PERFORMANCE at 100% of production, in its own `share_tier`
("performance", not "standard"). This is a real, defensible tradeoff,
not an oversight:

- **Subsetting undermines the very thing performance testing measures.**
  A load/performance test's entire purpose is to observe behavior under
  production-representative volume -- query plans that only degrade past
  a certain table size, index behavior, connection-pool exhaustion,
  cache eviction patterns. A 10%-scale "performance" environment would
  pass tests that a real production-scale deployment would fail, which
  is a worse outcome than the extra storage cost: a false negative that
  ships.
- **The other four environments (DEV, QA, SIT, UAT) legitimately can
  share.** Their target percentages (10%, 10%, 5%, 15%) differ, but none
  of them needs *scale-dependent* behavior to be meaningful -- a
  functional test, an integration test, or a UAT sign-off does not
  depend on production-scale row counts the way a performance test does.
  `illustrative_capacity_plan` models this honestly: the "standard" tier
  is sized to the *largest* requirement among its members (UAT's 15%),
  because a smaller requirement (SIT's 5%) can safely consume a larger,
  over-provisioned shared snapshot -- it can never safely consume a
  snapshot smaller than its own stated requirement.

Real, configured result from the default scenario (100 TB production):

```
Naive total (5 independent copies):  140.0 TB
  tier=standard   : shared snapshot = 15.0 TB   (covers DEV, QA, SIT, UAT)
  tier=performance: shared snapshot = 100.0 TB  (PERFORMANCE alone)
Shared total: 115.0 TB
Savings: 25.0 TB (17.9%)
```

Note this is a *smaller* savings percentage than the real 5-environment
example in section 3 (80%) -- and that gap is itself the honest lesson:
**savings from sharing are largest when environments' real requirements
are close together, and shrink (sometimes to zero) when one environment
has a requirement the others cannot share.** A capacity plan that
reports one number without breaking down its tiers hides this.

## 5. Subsetting and masking reduce realism, on purpose -- know what you're trading away

Every environment except PERFORMANCE in this platform's default model
uses subsetted, masked data smaller than production. That is the whole
point of Phase 4 (subsetting) and Phase 3 (masking) -- but it is not a
free lunch:

- **Rare edge cases become rarer.** A 10%-scale subset of production
  will, by construction, contain roughly 10% of however many instances
  of a rare condition/claim pattern exist in production. Phase 4's
  `risk_edge_case` strategy and Phase 5's synthetic scenario generation
  exist specifically to compensate for this (see item 6 below) -- but a
  plain percentage-based subset alone under-represents rare cases
  proportionally to its size.
- **Distribution shape at scale is not guaranteed.** `docs/problems/problems_phase_03.md`
  and `docs/CERTIFICATION_VS_MASKING.md` already document that this
  platform's masking does not verify dataset-wide statistical
  distribution preservation (mean/variance/percentile fidelity) -- a
  smaller dataset is one more variable on top of that.
- **Scale-dependent bugs are invisible below production scale**, per
  section 4's PERFORMANCE discussion -- this generalizes beyond
  performance testing specifically. A query that only becomes slow past
  a certain row count, a batch job that only OOMs at real volume, a
  partition skew that only appears with real cardinality: none of these
  reproduce in a 10%-scale environment, by definition.

## 6. Synthetic supplementation: coverage without proportional cost

Phase 5's synthetic scenario generation
(`data_plane.synthetic`) is the platform's actual answer to section 5's
"rare edge cases become rarer" problem, and it is worth naming
explicitly here because it changes the cost/realism tradeoff in a way
percentage-based subsetting alone cannot: a synthetic scenario (a
high-cost claim, an unusual prescription combination, a boundary date)
adds a *fixed*, small number of rows regardless of how large or small
the base subset is. Its storage cost does not scale with production
size the way a percentage-based subset does -- guaranteeing a rare
scenario's presence costs a constant, small amount of storage/compute,
not a proportional share of production's. This is precisely why Phase 6
runs synthetic generation *after* subsetting/masking rather than trying
to solve rare-case coverage by making the subset itself bigger.

## 7. Copy-on-write and vacuum/cleanup: concept mappings, not new infrastructure

Per the operational scope for this phase, these are documented as
mappings onto real, already-built Phase 7 mechanisms, not new
infrastructure:

- **Copy-on-write.** A Phase 7 refresh
  (`LifecycleRepository.refresh`) never mutates an existing
  `DatasetVersion` -- it registers a brand-new, immutable one (a fresh
  certification pipeline run) and atomically repoints
  `EnvironmentDatasetRequest.current_version_id` at it. The old version
  remains exactly as it was, still readable by any environment that
  hasn't moved, until retention/rollback/revocation changes its status.
  That "write new, atomically repoint, old stays valid" pattern is
  copy-on-write at the metadata-pointer level -- this platform does not
  implement block/file-level copy-on-write (e.g. a Delta Lake merge)
  anywhere; ADR-0007 already documents that most of this platform's
  Parquet output today is one-shot/immutable, not a Delta table updated
  in place.
- **Vacuum/cleanup.** `CapacityPlanner.vacuum_candidates` (new this
  phase, real and DB-backed) is the "what is safe to reclaim" query a
  real cleanup job would run: a `DatasetVersion` whose status is
  terminal-for-now (expired/revoked/rolled_back) *and* is referenced by
  zero `EnvironmentDatasetRequest`s. It is deliberately read-only --
  see `docs/problems/problems_phase_08.md` P8-3 for why this phase identifies
  candidates rather than deleting anything (no storage adapter exists
  yet to delete through, and an unattended auto-delete on a read-only
  query's say-so would be a dangerous default regardless).

## 8. What this phase still does not know

- It does not know real cloud storage *pricing* -- everything above is
  bytes, not dollars. A real deployment would multiply these byte
  figures by the actual per-GB/month rate of whatever storage tier
  (S3 Standard, S3 Infrequent Access, Azure Cool Blob, ...) each
  dataset version actually lives on, which this platform does not track
  (no storage adapter exists yet -- `docs/problems/problems_master.md` P0-3).
- It does not know real compute pricing either -- `estimator.py`'s
  compute-unit-hours are a row-count-based heuristic, not a cost figure
  from any real cloud billing API.
- It trusts `DatasetVersion.size_bytes`/`row_counts` as registered,
  rather than independently re-verifying them against `storage_uri`
  every time a plan is computed -- see `docs/problems/problems_phase_08.md` P8-2 for
  why closing that gap fully needs a real storage adapter, which this
  phase gives real measurement *tooling* for (`data_plane.capacity.footprint`)
  but does not wire into an enforced trust boundary.
