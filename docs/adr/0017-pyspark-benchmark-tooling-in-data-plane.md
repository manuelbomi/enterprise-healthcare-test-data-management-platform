# ADR-0017: PySpark scale/performance benchmark tooling lives in the data plane, runs local-mode only

## Status

Accepted

## Context

`ROADMAP.md` Phase 14 asks this repository to close a real, previously
documented gap: `services/data-plane`'s `pyproject.toml` has declared
`pyspark>=3.5`/`delta-spark>=3.1` as dependencies since Phase 0
(`ARCHITECTURE.md` section 2.2's "every job here is designed to be run
either locally ... or on Spark"), but no file under
`services/data-plane/src` ever imported `pyspark` or constructed a
`SparkSession` through Phase 13 -- every real engine (`discovery`,
`subsetting`, `masking`, `synthetic`, `certification`, `capacity`)
operates on local files with pandas/pyarrow/stdlib (see
`docs/problems/problems_phase_12.md`'s container-build decision record, which already
names this gap explicitly). Phase 14 needs two decisions:

1. **Where does real PySpark code, and the benchmark tooling that
   measures it, live?** Candidates: a new top-level `services/` (a
   "benchmark service"), inside `services/control-plane`, or inside
   `services/data-plane`.
2. **What does "real PySpark" mean when this repository's own
   infrastructure (`infra/`) has no Spark cluster -- only a developer's
   or reviewer's own machine?**

## Decision

### Where: `data_plane.spark` and `data_plane.benchmarks`, inside `services/data-plane`

Both new packages live under `services/data-plane/src/data_plane/`,
mirroring the exact precedent `ADR-0013` (Phase 8) already established
for `data_plane.capacity`: real, on-disk/in-process measurement and
transformation is data-plane territory by definition (every other
engine already there operates the same way, on filesystem paths, never
importing `control_plane`), and this phase's PySpark jobs are just two
more data-plane *transformations* (masking, subsetting) with a
different execution engine underneath -- not a new architectural plane,
and not control-plane orchestration (nothing in this phase adds a
`JobType`/API route; that remains the same not-yet-wired-up gap Phases
3/4 already documented in `ARCHITECTURE.md`'s own per-phase notes). A
standalone `services/benchmark-runner` (or similar) would duplicate
`data_plane.reference_data`/`data_plane.masking`/`data_plane.subsetting`
imports across a plane boundary for no real separation-of-concerns
benefit -- benchmarking these engines is not a distinct *responsibility*
the way discovery/masking/subsetting/certification are from each other;
it is instrumentation *of* them.

`data_plane.spark` (the real PySpark jobs: `session.py`,
`masking_job.py`, `subsetting_job.py`) and `data_plane.benchmarks` (the
measurement harness: `harness.py`, `report.py`) are two separate
packages, not one, because they answer different questions the same way
ADR-0013 split measurement from planning: `data_plane.spark` is
*production-shaped* code a real job orchestrator could eventually submit
(mirroring `data_plane.masking`/`data_plane.subsetting`'s own shape);
`data_plane.benchmarks` is *instrumentation* that times calls into either
the pandas-engine phases (3/4) or `data_plane.spark`, and is never itself
something a real pipeline run would invoke in production.

### What "real PySpark" means here: `local[*]` only, documented honestly

There is no Spark cluster anywhere in `infra/` (no `spark-worker`/
`spark-master` service in `infra/docker/docker-compose.yml` or
`infra/k8s/helm/`), and adding one is out of this phase's scope (a real
Kubernetes-native or standalone Spark cluster is a substantial
infrastructure undertaking on its own, and Phase 12 already made the
deliberate choice not to containerize `data-plane` at all --
`docs/problems/problems_phase_12.md`). Every `SparkSession` this phase builds
(`data_plane.spark.session.get_local_spark_session`) therefore uses
`master("local[*]")` -- real Catalyst query plans, real Arrow-vectorized
`pandas_udf` execution, real broadcast joins, real wall-clock numbers,
but one JVM process on one machine, not a distributed executor fleet.
Every benchmark report this phase produces (`docs/SCALE_AND_PERFORMANCE.md`)
says this explicitly rather than implying cluster-scale behavior was
measured -- the same honesty convention `docs/CAPACITY_COST_TRADEOFFS.md`
(Phase 8) and `docs/COMPLIANCE_EVIDENCE.md` (Phase 13) already
established for numbers this repository reports.

### Which operations get a real Spark reimplementation

Not every Phase 3/4 masking/subsetting technique -- only the two that
most plausibly benefit from horizontal scaling, per `ROADMAP.md` Phase
14's own instruction to pick rather than reimplement everything:

- **Masking a wide, row-independent column** (`data_plane.spark.masking_job`):
  every row's masked value depends only on that row's own value, scope,
  and key (ADR-0006) -- no shuffle needed at all, and the per-row cost
  (one HMAC-SHA256 call) is small enough that Python call overhead
  dominates, which is exactly what a `pandas_udf` (Arrow-batched, not
  one Python call per row) is for.
- **Subsetting via referential closure, reimplemented as two broadcast
  joins** (`data_plane.spark.subsetting_job`): `data_plane.subsetting.closure`'s
  pandas graph walk *is* a join (filter a large table down to rows
  referencing a small selected set); a join between one large table and
  one small table is the textbook broadcast-join case, and the
  concrete operation this phase is required to document alongside
  shuffle behavior.

Both jobs reuse the real Phase 3 (`MaskingEngine`)/Phase 8
(`measure_directory_footprint`) code they are built on rather than
reimplementing masking logic or footprint measurement a second time --
`data_plane.spark.masking_job._hmac_pseudonymize_udf` wraps
`data_plane.masking.engine.MaskingEngine` directly, and
`tests/spark/test_masking_job.py::test_masked_member_id_matches_pandas_engine`
proves the two produce byte-for-byte identical tokens under the same
key/scope.

### Delta Lake: documented, not executed, this phase

`ADR-0007` already chose Delta Lake for versioned/mutable tables. This
phase does not add a real Delta write: doing so would require Delta's
Maven coordinates (`io.delta:delta-spark_*`) to be resolvable at
`SparkSession` construction time in every environment this repository
might be reviewed in (a live network fetch of JVM artifacts on first
use, with no guarantee of a warm local Ivy/Maven cache), which is a much
larger and more fragile new runtime dependency than this phase's actual
scope (benchmark tooling) warrants. `delta-spark` remains a declared
dependency for a later phase to wire up for real; this phase documents
Delta's optimization concepts (transaction log, `OPTIMIZE`, `ZORDER`,
`VACUUM`) conceptually in `data_plane/spark/README.md` instead of
fabricating "measured" Delta numbers -- consistent with this ADR's own
honesty rule above.

## Consequences

- `data_plane.spark`/`data_plane.benchmarks` can be exercised, and
  tested, completely independently of `control_plane` or any running
  infrastructure beyond a local JVM -- exactly how every other
  data-plane engine's tests already work (`tests/spark/`,
  `tests/benchmarks/`).
- Real numbers in `docs/SCALE_AND_PERFORMANCE.md` are honestly scoped to
  "this machine, `local[*]`" -- a reviewer cannot mistake them for
  cluster-scale numbers, and this ADR is the durable record of why no
  cluster-scale number is reported (there is nothing to measure it on).
- Windows-specific local-mode friction (a native `winutils.exe`/
  `HADOOP_HOME` shim required for local file writes, and a worker-
  interpreter-mismatch crash fixed by pinning `PYSPARK_PYTHON`/
  `PYSPARK_DRIVER_PYTHON` to `sys.executable`) is real, was reproduced in
  this repository's own development environment while implementing this
  phase, and is fixed once in `data_plane.spark.session` rather than left
  for every future contributor on Windows to rediscover independently --
  see that module's docstring and `data_plane/spark/README.md`.
- This phase still does not wire a `JobType.SPARK_MASKING`/
  `SPARK_SUBSETTING` into the control plane's orchestrator -- the same
  "engine exists, job submission plumbing does not yet" gap `ARCHITECTURE.md`'s
  Phase 3/4 notes already document for the pandas-engine versions of
  these same two operations. Tracked, not reopened, in
  `docs/problems/problems_phase_14.md`.
- No real Delta table exists anywhere in this repository after this
  phase either -- `docs/problems/problems_phase_14.md` tracks this as a genuinely open
  item for whichever later phase actually needs Delta's transaction-log/
  time-travel semantics, not something this phase's benchmark-tooling
  scope was ever going to close.
