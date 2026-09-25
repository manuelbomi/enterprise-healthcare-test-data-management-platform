# `data_plane.spark`

Real PySpark implementations of the two data-plane operations most likely
to benefit from horizontal scaling (Phase 14): masking a wide claims
table (`masking_job.py`) and subsetting via broadcast join
(`subsetting_job.py`), both running on a **local Spark session**
(`session.py`) -- see `docs/SCALE_AND_PERFORMANCE.md` for real measured
numbers and `docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md`
for why this package exists in the data plane at all.

## What actually runs here vs. what is documented conceptually

This repository has no real Spark cluster (`infra/` has no
`spark-worker`/`spark-master` service -- `problems_phase_12.md`'s
container-build note already says so). Every job in this package runs
against `SparkSession.builder.master("local[*]")` -- real PySpark APIs,
real Catalyst query plans, real Arrow-vectorized UDF execution, real
wall-clock numbers, but **one JVM process on one machine**, not a
distributed executor fleet. Concretely:

| Concept | Demonstrated how |
|---|---|
| Partitioning | Real. `claim/batch=claims-2024Q4/`, `claim/batch=claims-2025Q1/` are real Hive-style partitions (`reference_data/writers/parquet_writer.py`); both jobs read/write them, and `run_claims_masking_job`'s writer re-partitions by `batch`. |
| Predicate pushdown | Real. `run_claims_masking_job(..., status_filter=...)` filters on `status` before any column is masked; against Parquet's per-row-group min/max statistics, Spark pushes this into the file scan (`df.explain()` shows `PushedFilters: [*IsNotNull(status), *EqualTo(status,...)]`) -- see "How to see this yourself" below. |
| Broadcast joins | Real. `subsetting_job.py`'s two joins both use `F.broadcast(...)` explicitly. |
| Caching | Real, demonstrated in `tests/spark/test_masking_job.py::test_repeated_read_benefits_from_cache` -- see below. |
| Schema evolution / merge | Real. Both jobs read `claim/` with `option("mergeSchema", "true))` to reconcile the legacy `paid_amount` batch and the current `amount_paid`/`adjustment_reason_code` batch into one DataFrame. |
| Small-file problem | Real, observed. See below. |
| Shuffle behavior | Real for the parts of the jobs that do shuffle (`.distinct()`); the joins themselves are deliberately shuffle-free (broadcast). |
| Skew | **Not reproduced from real measurement** -- this estate's synthetic member->claim fan-out is randomized within a bounded max per `ScaleProfile` (`reference_data/scale.py`), so it does not manufacture a realistically skewed key. Documented conceptually below, honestly labeled as such. |
| Delta Lake optimization (`OPTIMIZE`, `ZORDER`, `VACUUM`, transaction log) | **Not executed** -- this environment has no cached Delta Lake Maven coordinates (`io.delta:delta-spark_*`) resolvable without a network fetch at Spark-submit time in every review environment this repository might run in, and Phase 14's scope is benchmark tooling, not adding a new hard runtime dependency on Maven-artifact resolution. `delta-spark` remains a declared dependency (`pyproject.toml`, per ADR-0007) for a later phase to actually wire up; this phase documents the concepts conceptually below instead of fabricating "measured" Delta numbers. See `problems_phase_14.md`. |
| Autoscaling | **Not applicable to `local[*]`** by construction -- documented conceptually below. |

## Windows: `winutils.exe`/`HADOOP_HOME`

Local-mode PySpark's file-*write* path (not read) requires a native
Hadoop shim on Windows. Run this once, if you are on Windows:

```
python scripts/setup_local_spark_windows.py
```

`data_plane.spark.session.get_local_spark_session` auto-detects the
downloaded runtime (`.spark-runtime/hadoop-3.3.6/`, git-ignored) on every
call; nothing else needs to change. See `session.py`'s module docstring
for the full account and the exact JVM error this avoids.

## Partitioning and the small-file problem

Reading the real `performance`-scale estate's `claim_line/` table (one
`part-0000.parquet` file, ~300K rows -- see
`reference_data/writers/parquet_writer.py`) and writing it back
unpartitioned with the default `spark.sql.shuffle.partitions=200`
produces **200 output files for ~300K rows** (~1,500 rows/file) -- the
small-file problem, reproduced directly: too many small files, each
carrying fixed per-file overhead (footer metadata, an S3/ADLS API call
per file to open), that a real object-store-backed lower environment
would pay for on every subsequent read. `session.get_local_spark_session`
sets `spark.sql.shuffle.partitions=8` by default specifically to avoid
manufacturing this problem in this phase's own benchmark runs (see its
docstring); `docs/SCALE_AND_PERFORMANCE.md`'s "Shuffle behavior" section
shows the measured file count at both settings.

The general rule this demonstrates: partition/shuffle-partition count
should be sized to data volume (rule of thumb: target 128MB-1GB per
output file), not left at a cluster-wide default tuned for a much larger
job.

## Shuffle behavior

`run_claims_masking_job` has **no shuffle stage at all** -- masking a
column is a row-local `withColumn`/`pandas_udf` map, and `df.explain()`
shows a single `*(1) Project` node over the file scan, no `Exchange`.

`run_member_subsetting_job` shuffles exactly once per job run, for
`.distinct()` on the (small) sampled `member_id`/`claim_id` projections
(an exact-dedup hash-partitioned aggregation) -- but the two actual
*joins* against the large `claim`/`claim_line` tables are broadcast
joins, so the large tables themselves are never shuffled. Contrast this
with what a naive `claims.join(large_member_table, "member_id")` between
two genuinely large tables would do: a sort-merge join, which shuffles
*both* sides across the network -- exactly the cost this phase's design
choice (broadcast the small side) avoids. See
`docs/SCALE_AND_PERFORMANCE.md` for `df.explain()` output captured from a
real run.

## Broadcast joins

See `subsetting_job.py`'s module docstring and inline comments --
`F.broadcast(member_sample)` and `F.broadcast(subset_claim_ids)` are the
two real broadcast joins. Spark's cost-based optimizer would likely pick
a broadcast join here automatically once the small side's estimated size
drops under `spark.sql.autoBroadcastJoinThreshold` (default 10MB) even
without the explicit hint, given how small a member/claim-id sample is
relative to that threshold -- the explicit `F.broadcast(...)` hint is
used anyway so the choice is documented in the code itself, not left to
be silently correct only as long as the optimizer's heuristic keeps
agreeing with it as data volume grows.

## Skew (documented, not reproduced)

Data skew -- one join/group-by key (e.g. one exceptionally
high-claim-volume member) holding a disproportionate share of the rows --
causes one Spark task to do dramatically more work than its siblings,
so the *slowest* task (not the average) determines stage wall-clock
time. Real mitigations: salting the skewed key before a shuffle join,
Adaptive Query Execution's skew-join optimization (`spark.sql.adaptive.
skewJoin.enabled`, on by default in Spark 3.x+, enabled implicitly here
via `spark.sql.adaptive.enabled=true` in `session.py`), or splitting the
skewed key into its own dedicated pass. This repository's synthetic
estate (`reference_data/scale.py`'s bounded-random fan-out) does not
produce a realistically skewed key distribution, so no skew number is
reported here as measured -- doing so would fabricate a number Phase 8's
and Phase 13's honesty conventions explicitly forbid (see
`docs/CAPACITY_COST_TRADEOFFS.md`, `docs/COMPLIANCE_EVIDENCE.md`).

## Caching

`tests/spark/test_masking_job.py::test_repeated_read_benefits_from_cache`
measures a real, reproducible effect: reading and counting the same
DataFrame twice without `.cache()` re-executes the Parquet scan (and, for
the masked DataFrame, re-runs the `pandas_udf`) each time; calling
`.cache()` (or `.persist()`) after the first action materializes the
result in memory (`local[*]` executor memory, i.e. this JVM's heap) so
the second action skips re-computation. The general rule: cache a
DataFrame you are about to reuse across multiple actions, and only that
DataFrame -- caching something read/used exactly once wastes memory for
no benefit.

## Predicate pushdown

`run_claims_masking_job(..., status_filter="PAID")`'s `df.explain()`
shows `PushedFilters` in the `FileScan parquet` node -- Spark hands the
filter to the Parquet reader itself, which can skip whole row groups
using their embedded min/max column statistics without ever
deserializing rows that cannot match, rather than reading every row and
filtering in Spark's own execution engine afterward. See
`docs/SCALE_AND_PERFORMANCE.md` for a real captured `explain()` plan.

## Delta Lake optimization concepts (documented, not executed this phase)

`docs/adr/0007-delta-parquet-data-format.md` already chose Delta Lake for
versioned/mutable tables; this phase does not add a real Delta write (see
the table above for why), but documents the concepts a later phase's real
Delta adoption would rely on:

- **Transaction log (`_delta_log/`)**: every write is an atomic, versioned
  commit; readers see a consistent snapshot even during a concurrent
  writer's commit, and `VERSION AS OF`/`TIMESTAMP AS OF` time-travel reads
  an older commit without needing a separate physical copy.
- **`OPTIMIZE` (compaction)**: rewrites many small files into fewer,
  larger ones -- the real fix for the small-file problem this README
  reproduces above, applied after the fact rather than tuned for up
  front.
- **`ZORDER BY`**: co-locates rows with similar values of the Z-ordered
  column(s) within the same files, so a predicate-pushdown filter on that
  column skips more files, not just more row groups within one file.
- **`VACUUM`**: physically deletes files no longer referenced by any
  retained transaction-log version, after a retention window -- without
  it, every historical version's files accumulate forever.

## Autoscaling considerations (not applicable to `local[*]`, documented conceptually)

`local[*]` has a fixed core count (this machine's CPU count) for the
lifetime of the process -- there is no "scale out" to demonstrate.  On a
real cluster (Databricks, EMR, a Kubernetes-native Spark deployment),
autoscaling adds/removes *executors* between (not within) stages, based
on pending-task backlog; the concrete tradeoffs a real deployment has to
account for:

- Executors added mid-job do not help a stage that is already
  bottlenecked on a small number of skewed tasks (see "Skew" above) --
  autoscaling adds parallelism, it does not fix an uneven work split.
- Scale-*down* is riskier than scale-up for a job with any shuffle: an
  executor holding shuffle data that gets decommissioned before that data
  is consumed forces a recompute of the lost partitions.
- Cold-start latency (new executor JVM startup, container scheduling)
  makes autoscaling a poor fit for short, bursty jobs relative to
  provisioning a fixed, right-sized cluster for a known workload shape --
  which is the same "capacity planning" tradeoff Phase 8
  (`docs/CAPACITY_COST_TRADEOFFS.md`) already made for storage/compute
  footprint, applied here to compute elasticity specifically.

## How to see this yourself

```python
from data_plane.spark.session import get_local_spark_session
from data_plane.spark.masking_job import run_claims_masking_job
from data_plane.masking.secrets import resolve_hmac_key

spark = get_local_spark_session("demo")
df = spark.read.option("mergeSchema", "true").parquet(
    "data/tmp/synthetic-estate/object_storage_claims_parquet/claims-warehouse/claim"
)
df.filter(df.status == "PAID").explain()  # look for PushedFilters
```
