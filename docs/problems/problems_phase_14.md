# Problems — Phase 14 (Scale and Performance Engineering)

Written before implementation, per `CONTRIBUTING.md`. Updated after
implementation to record what was actually resolved vs. what remains
open (moved to `docs/problems/problems_master.md` if broader than this phase).

## Context this phase starts from

`services/data-plane`'s `pyproject.toml` has declared
`pyspark>=3.5`/`delta-spark>=3.1` as dependencies since Phase 0, but no
file under `services/data-plane/src` has ever imported `pyspark` or
constructed a `SparkSession` through Phase 13 — every real engine
(`reference_data`, `discovery`, `subsetting`, `masking`, `synthetic`,
`certification`, `capacity`) operates on local files (SQLite/Parquet/
NDJSON/CSV) with pandas/pyarrow/stdlib, not Spark (already documented in
`docs/problems/problems_phase_12.md`'s container-build decision record). This phase is
where the spec explicitly asks for real PySpark implementations.
There is also no real Spark cluster anywhere in this repository's
infrastructure (`infra/` has no `spark-worker`/`spark-master` service) —
whatever runs this phase's PySpark code runs `local[*]` on a single
machine.

Risks identified before implementation, and how they were resolved:

- **A benchmark that fabricates or extrapolates a "distributed cluster"
  number would violate this repository's own honesty conventions**
  (`docs/CAPACITY_COST_TRADEOFFS.md`, `docs/COMPLIANCE_EVIDENCE.md`).
  Resolved: every number in `docs/SCALE_AND_PERFORMANCE.md` was actually
  measured by running `data_plane.benchmarks.cli` in this repository's
  own development environment against `local[*]`, and the report/README
  say so explicitly rather than implying cluster-scale behavior.
- **Building a second synthetic-data generator "for benchmarking" would
  duplicate Phase 1's real, already-configurable `ScaleProfile` system.**
  Resolved: `data_plane.benchmarks.harness.benchmark_dataset_generation`
  calls the real `EstateGenerator`/`write_estate` at a caller-selected
  named profile (`tiny`/`developer`/`qa`/`performance`) — no second
  generator was written.
- **PySpark on Windows (the actual development platform this phase was
  implemented on) has two real, previously-undocumented local-mode
  failure modes that would otherwise block every one of this phase's own
  benchmark runs** — found and fixed while implementing this phase, not
  hypothetical:
  1. Local file *writes* fail with `java.io.FileNotFoundException:
     HADOOP_HOME and hadoop.home.dir are unset` without a native
     `winutils.exe`/`hadoop.dll` shim on `PATH`/`HADOOP_HOME`. Resolved:
     `scripts/setup_local_spark_windows.py` (opt-in, downloads a pinned
     community-maintained shim into git-ignored `.spark-runtime/`) +
     `data_plane.spark.session.configure_windows_hadoop_runtime`
     (auto-detects it, or raises a clear, actionable error instead of
     letting a caller hit the raw JVM stack trace).
  2. Any Python UDF (plain or `pandas_udf`) crashed the JVM-launched
     worker process outright (`SparkException: Python worker exited
     unexpectedly (crashed)`, `IOException: An established connection
     was aborted`, with **no Python traceback at all**) whenever the
     worker resolved a *different* `python`/`python3` on `PATH` than the
     interpreter that built the `SparkSession` (this machine has three
     separate Python installations on `PATH`) — a real, silent, hard-to-
     diagnose failure mode on any multi-Python-install machine, not
     specific to this one. Resolved:
     `data_plane.spark.session.pin_worker_python_interpreter` sets
     `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` to `sys.executable` unless
     the caller already set one, called on every
     `get_local_spark_session` invocation.
- **Reimplementing every Phase 3 masking technique or every Phase 4
  subsetting strategy in Spark would be a much larger PySpark
  reimplementation than "operations that should scale horizontally"
  calls for.** Resolved: exactly two operations were chosen and
  implemented for real —
  `data_plane.spark.masking_job.run_claims_masking_job` (a `pandas_udf`
  reusing Phase 3's real `MaskingEngine`, masking the claims-warehouse
  `claim` table's direct identifiers — no shuffle needed, the
  embarrassingly-parallel case) and
  `data_plane.spark.subsetting_job.run_member_subsetting_job` (two
  explicit broadcast joins reimplementing Phase 4's referential-closure
  concept for one selection strategy — the large-table/small-table join
  case). See `docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md`
  for the full reasoning on scope and package placement.

## Resolved by this phase

- `services/data-plane/src/data_plane/spark/` (`session.py`,
  `masking_job.py`, `subsetting_job.py`, `cli.py`) — real, runnable
  PySpark code, closing the gap `docs/problems/problems_phase_12.md` first identified.
- `services/data-plane/src/data_plane/benchmarks/` (`harness.py`,
  `report.py`, `cli.py`) — real benchmark tooling measuring records/sec,
  masking throughput (pandas vs. Spark), subsetting throughput (pandas
  vs. Spark), dataset generation time, validation time, storage
  footprint, and compression ratio, all against a real, freshly
  generated estate at a configurable scale profile.
- `docs/SCALE_AND_PERFORMANCE.md` — real benchmark reports (at `qa` and
  `performance` scale) run in this repository's own development
  environment, plus the required documentation of partitioning, shuffle
  behavior, broadcast joins, skew, caching, predicate pushdown, Delta
  optimization concepts, the small-file problem, and autoscaling
  considerations (the last three, and skew, documented conceptually —
  see "Left open" below for why).
- `scripts/setup_local_spark_windows.py` and the two Windows-local-mode
  fixes described above.
- 26 new tests: `services/data-plane/tests/spark/` (17: `test_session.py`,
  `test_masking_job.py`, `test_subsetting_job.py`) and
  `services/data-plane/tests/benchmarks/` (9: `test_harness.py`,
  `test_report.py`) — all against real Spark sessions and real, on-disk
  generated estates, no mocking of Spark or the filesystem.

## Left open

- **P14-1 (open, by design)** — No real Delta Lake table is written
  anywhere in this repository after this phase. `ADR-0007` chose Delta
  for versioned/mutable tables, but this phase does not add a real Delta
  write (see ADR-0017's "Delta Lake: documented, not executed" section
  for why: no cached Delta Maven coordinates can be assumed present in
  every environment this repository is reviewed in, and this phase's
  scope is benchmark tooling, not adopting a new hard runtime
  dependency). Delta's optimization concepts (transaction log,
  `OPTIMIZE`, `ZORDER`, `VACUUM`) are documented conceptually in
  `data_plane/spark/README.md`, not demonstrated with real "before/after"
  numbers. A later phase that actually needs Delta's ACID/time-travel
  semantics should close this.
- **P14-2 (open, by design)** — Data skew is documented conceptually
  (`data_plane/spark/README.md`) but not reproduced with a real
  measurement. The Phase 1 estate's member->claim fan-out
  (`reference_data/scale.py`'s bounded-random-per-member counts) does
  not manufacture a realistically skewed join/group-by key, and
  fabricating one purely to report a "skew number" would violate this
  repository's honesty conventions more than it would teach anything
  real. A future phase wanting a real skew measurement would need to
  inject a deliberately skewed key distribution into the estate
  generator first (out of this phase's scope).
- **P14-3 (open, by design)** — Autoscaling is not applicable to
  `local[*]` by construction (a fixed core count for the process's
  lifetime) and is documented conceptually only, per ADR-0017's decision
  not to stand up a real Spark cluster in this repository's
  infrastructure for this phase.
- **P14-4 (open)** — Neither `data_plane.spark.masking_job` nor
  `data_plane.spark.subsetting_job` is wired into the control plane's
  job orchestrator (`JobType`/`JobRequest` in `libs/contracts` do not
  gain a Spark-specific variant this phase) — the same "engine exists,
  job-submission plumbing does not yet" gap `ARCHITECTURE.md`'s Phase
  3/4 notes already document for the pandas-engine versions of masking
  and subsetting. Running either job today means calling
  `data_plane.spark.cli` directly or importing the module, exactly like
  every other data-plane engine before this phase.
- **P14-5 (open, by design)** — `run_claims_masking_job` masks only the
  claims-warehouse `claim` table's two direct-identifier columns
  (`member_id`, `claim_id`), not Phase 3's full masking policy (date
  shifting, format-preserving synthetic replacement, tokenization, ...).
  Reimplementing every technique in Spark was out of this phase's "pick
  the operations that most plausibly benefit from horizontal scaling"
  scope — see `data_plane/spark/masking_job.py`'s
  `DEFAULT_MASKED_COLUMNS` docstring. Consequently, `pandas_masking` (the
  full estate, every technique) and `spark_masking` (one table, two
  columns, one technique) in `docs/SCALE_AND_PERFORMANCE.md` are not a
  pure apples-to-apples technique-for-technique race, and the report says
  so explicitly rather than implying they are.
- **P14-6 (open, by design)** — The two Windows-local-mode fixes this
  phase makes (`configure_windows_hadoop_runtime`,
  `pin_worker_python_interpreter`) are only exercised for real on a
  Windows machine; this repository's own CI (`.github/workflows/ci.yml`,
  `runs-on: ubuntu-latest`) never needs either code path (Linux needs no
  `winutils.exe` shim, and this CI environment does not have multiple
  Python installations on `PATH`). `tests/spark/test_session.py` proves
  the logic correctly by monkeypatching `sys.platform`/environment
  variables rather than relying on ever actually running on Windows CI —
  documented here so a future contributor does not mistake "passes on
  Linux CI" for "verified on Windows" without reading the test file.
