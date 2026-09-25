# Scale and performance engineering: real numbers, and what they do and do not show

This document is required reading before treating any number Phase 14
(`services/data-plane/src/data_plane/spark`,
`services/data-plane/src/data_plane/benchmarks`) produces as more
universal than it actually is. It follows the same honest tone
`docs/CAPACITY_COST_TRADEOFFS.md` (Phase 8) and
`docs/COMPLIANCE_EVIDENCE.md` (Phase 13) already established: every
number below comes from a real run of `python -m
data_plane.benchmarks.cli` in this repository's own development
environment (Windows, `local[*]` PySpark, no real cluster) -- nothing
here is modeled, extrapolated, or fabricated. See
`docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md` for why this
scope stops where it does.

## 1. Environment these numbers came from

| | |
|---|---|
| Platform | `Windows-11-10.0.26200-SP0` |
| CPU count | 28 |
| Python | 3.14.4 |
| PySpark | 4.2.0 |
| Spark master | `local[*]` -- **one JVM process on one machine, not a distributed cluster** (`infra/` has no `spark-worker`/`spark-master` service) |
| HMAC key | a throwaway, run-scoped dev key, never persisted |

Reproduce with:

```
cd services/data-plane
python scripts/../../../scripts/setup_local_spark_windows.py   # Windows only, one-time
export TDM_MASKING_HMAC_KEY=$(python -m data_plane.masking.cli --generate-dev-key)
python -m data_plane.benchmarks.cli --scale qa --out-dir data/tmp/phase14-benchmarks
python -m data_plane.benchmarks.cli --scale performance --out-dir data/tmp/phase14-benchmarks-perf
```

## 2. `qa` scale (81,295 rows across the estate; 10,726 claims)

| Operation | Rows | Elapsed (s) | Records/sec | Notes |
|---|---|---|---|---|
| `dataset_generation[qa]` | 81,295 | 3.312 | 24,543 | Phase 1 `EstateGenerator` + `write_estate` |
| `storage_footprint[raw_estate]` | 13 files | 0.241 | -- | mean Parquet compression ratio **2.85x** vs. CSV re-encoding |
| `pandas_masking[full_estate]` | 81,295 | 34.963 | 2,325 | Phase 3 `mask_estate`, every table/technique, row-by-row Python |
| `pandas_masking_validation` | 1,150 linkage samples | 0.000 | 3,981,995 | Phase 3 `validate_masking_run`; `passed=True` |
| `pandas_subsetting[2.0%]` | 868 (claim+claim_line) | 1.028 | 844 | Phase 4 `run_subsetting`, 51 of 2,550 members selected |
| `spark_masking[claim]` | 10,726 | 6.284 | **1,707** | Phase 14 `pandas_udf`, `member_id`+`claim_id` only |
| `spark_subsetting[2%]` | 731 (claim+claim_line) | 2.762 | 265 | 2 broadcast joins, 35 of 2,550 members, selectivity 0.0169 |
| `storage_footprint[pandas_masked]` | 12 files | 0.278 | -- | mean Parquet compression ratio **2.31x** |

## 3. `performance` scale (766,252 rows across the estate; 105,936 claims)

| Operation | Rows | Elapsed (s) | Records/sec | Notes |
|---|---|---|---|---|
| `dataset_generation[performance]` | 766,252 | 30.825 | 24,858 | ~9.4x `qa`'s row volume |
| `storage_footprint[raw_estate]` | 13 files | 1.285 | -- | mean Parquet compression ratio **3.21x** |
| `pandas_masking[full_estate]` | 766,252 | 285.808 (4m46s) | 2,681 | every table/technique |
| `pandas_masking_validation` | 1,150 linkage samples | 0.000 | 3,589,263 | `passed=True` |
| `pandas_subsetting[2.0%]` | 7,782 | 8.777 | 887 | 408 of 20,400 members selected |
| `spark_masking[claim]` | 105,936 | 8.332 | **12,714** | same two columns as `qa` |
| `spark_subsetting[2%]` | 7,640 | 2.982 | 2,562 | 360 of 20,400 members, selectivity 0.0192 |
| `storage_footprint[pandas_masked]` | 12 files | 1.629 | -- | mean Parquet compression ratio **2.59x** |

## 4. What these numbers actually show (and what they do not)

**Spark's fixed per-job overhead dominates at `qa` scale, and stops
dominating by `performance` scale.** `spark_masking[claim]`'s
records/sec went from 1,707 (`qa`, 10,726 claim rows) to 12,714
(`performance`, 105,936 claim rows) -- a **7.4x throughput increase for
a 9.9x row-count increase**, i.e. Spark's per-row cost stayed roughly
flat while its fixed overhead (query planning, Arrow batch setup,
JVM<->Python worker round trips) amortized over far more rows. This is
the real, measured version of the textbook claim "Spark has more fixed
overhead than a simple loop, so it needs enough data to be worth it" --
at `qa` scale, that overhead is not yet worth paying; the crossover
point for *this specific job, on this specific machine* is somewhere
between 10K and 106K claim rows.

**This is not a clean pandas-vs-Spark apples-to-apples race.**
`pandas_masking[full_estate]` masks *every table and technique* in the
whole estate (14 entities, 8 masking techniques); `spark_masking[claim]`
masks *two columns of one table* with one technique
(`HMAC_PSEUDONYMIZATION`) -- see `problems_phase_14.md` P14-5 for why
(reimplementing Phase 3's full policy in Spark was out of this phase's
scope). Their absolute elapsed times reflect different total amounts of
work, not the same work done two ways. What *is* directly comparable is
the *shape* of the throughput curve as row count grows by ~10x, which is
the "beyond laptop-sized data" story this phase is required to
demonstrate.

**Dataset generation throughput (~24,500-25,000 rows/sec) barely moved
between a ~10x change in row count**, because `EstateGenerator` is a
single-pass, mostly-CPU-bound Python loop with no I/O-bound step that
would start to dominate at this row-count range on this hardware.

**Storage footprint and compression ratio scale as expected: absolute
bytes grow roughly linearly with row count (10.7MB at `qa`, 98.0MB at
`performance`, matching the ~9.2x row-count ratio), and the real Parquet
compression ratio measured against these entities' actual data
(3.21x-2.85x uncompressed-CSV-equivalent to compressed-Parquet) is
consistent with Phase 8's own finding that Parquet's advantage grows
with row count** (`docs/CAPACITY_COST_TRADEOFFS.md` measured Parquet
*losing* to CSV at `tiny` scale's handful of rows per file).

## 5. Real captured Spark behavior (not paraphrased)

**Predicate pushdown** — filtering `claim` by `status == "paid"` before
masking (`run_claims_masking_job(..., status_filter="paid")`) produces
this real physical plan (captured with `df.filter(...).explain()`
against the `qa`-scale estate):

```
*(1) Filter (isnotnull(status#5) AND (status#5 = paid))
+- *(1) ColumnarToRow
   +- FileScan parquet [...] Batched: true,
      DataFilters: [isnotnull(status#5), (status#5 = paid)],
      PushedFilters: [IsNotNull(status), EqualTo(status,paid)], ...
```

`PushedFilters` (not just `DataFilters`) proves the filter was handed to
the Parquet reader itself, not applied after a full read.

**Broadcast join** — `claims.join(F.broadcast(member_sample),
on="member_id")` produces this real physical plan (same estate):

```
AdaptiveSparkPlan isFinalPlan=false
+- Project [...]
   +- BroadcastHashJoin [member_id#1], [member_id#19], Inner, BuildRight, false, false
      :- Filter isnotnull(member_id#1)
      :  +- FileScan parquet [...]  -- the large `claim` table, read once, never shuffled
      +- BroadcastExchange HashedRelationBroadcastMode(...)
         +- ... -- the small sampled-member-id side, broadcast to every executor
```

`BroadcastHashJoin`/`BroadcastExchange` (not `SortMergeJoin`/`Exchange
hashpartitioning` on the large side) proves the large `claim` table was
never shuffled.

**Small-file problem** — writing the real `qa`-scale `claim_line` table
(30,030 rows) with Spark's cluster-tuned default
(`spark.sql.shuffle.partitions=200`) produced **200 output files**
(~150 rows/file); writing the identical data with this package's
laptop-appropriate default (`spark.sql.shuffle.partitions=8`, set by
`data_plane.spark.session.get_local_spark_session`) produced **8 output
files** (~3,754 rows/file) -- both real, both measured against the same
input, same machine, same run. The 200-file case reproduces the small-
file problem directly: 200 files carrying fixed per-file overhead
(footer metadata, one object-store API call per file to open) for a
table that fits comfortably in far fewer, larger files.

## 6. What is documented conceptually, not measured (and why)

| Concept | Why not measured here |
|---|---|
| Data skew | The Phase 1 estate's bounded-random member->claim fan-out (`reference_data/scale.py`) does not produce a realistically skewed key -- fabricating one just to report a number would violate this document's own honesty rule. See `data_plane/spark/README.md` and `problems_phase_14.md` P14-2. |
| Delta Lake `OPTIMIZE`/`ZORDER`/`VACUUM`/transaction log | No real Delta write is executed this phase (ADR-0017) -- no cached Delta Maven artifact can be assumed present in every review environment. See `problems_phase_14.md` P14-1. |
| Autoscaling | Not applicable to `local[*]` by construction -- there is no cluster to scale. See `problems_phase_14.md` P14-3. |

See `services/data-plane/src/data_plane/spark/README.md` for the full
conceptual explanation of each, and `services/data-plane/src/data_plane/benchmarks/README.md`
for how to run this suite yourself and reproduce every number above.
