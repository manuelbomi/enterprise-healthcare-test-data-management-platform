# `data_plane.benchmarks`

Real benchmark measurements for `ROADMAP.md` Phase 14, run against a
real, generated synthetic estate. See `docs/SCALE_AND_PERFORMANCE.md` for
the actual numbers a run in this repository's own development
environment produced -- this README documents how the tooling works, not
what it measured.

## What is measured

| Metric (`ROADMAP.md` Phase 14) | Function | Reuses |
|---|---|---|
| Dataset generation time / records-per-sec | `harness.benchmark_dataset_generation` | Phase 1 `data_plane.reference_data` |
| Masking throughput (pandas baseline) | `harness.benchmark_pandas_masking` | Phase 3 `data_plane.masking.dataset_masker.mask_estate` |
| Masking throughput (Spark) | `harness.benchmark_spark_masking` | Phase 14 `data_plane.spark.masking_job` |
| Subsetting throughput (pandas baseline) | `harness.benchmark_pandas_subsetting` | Phase 4 `data_plane.subsetting.engine.run_subsetting` |
| Subsetting throughput (Spark) | `harness.benchmark_spark_subsetting` | Phase 14 `data_plane.spark.subsetting_job` |
| Validation time | `harness.benchmark_pandas_masking_validation` | Phase 3 `data_plane.masking.validation.validate_masking_run` |
| Storage footprint / compression ratio | `harness.benchmark_storage_footprint` | Phase 8 `data_plane.capacity.footprint.measure_directory_footprint` |

Every `benchmark_*` function returns `(real_result_object, BenchmarkResult)`
-- the real object the underlying engine call produced (a
`MaskingRunReport`, a `SubsettingRunResult`, a `SparkMaskingResult`, ...)
alongside the timing/row-count wrapper every function returns uniformly,
so a caller that wants more detail than `BenchmarkResult.extra` carries
always has it.

## Running it

```
cd services/data-plane
export TDM_MASKING_HMAC_KEY=$(python -m data_plane.masking.cli --generate-dev-key)
python -m data_plane.benchmarks.cli --scale qa --out-dir data/tmp/phase14-benchmarks
```

`--scale` accepts any `data_plane.reference_data.scale.SCALE_PROFILES`
name (`tiny`/`developer`/`qa`/`performance`). `performance` (20,000
members, ~765K total rows in this repository's own measured run -- see
`docs/SCALE_AND_PERFORMANCE.md`) is the "beyond laptop-sized data" volume
`ROADMAP.md` Phase 14 asks this phase to demonstrate; `qa` is used by
this package's own automated tests (faster, still large enough to show a
real pandas-vs-Spark throughput difference).

## Honesty conventions (same as Phase 8/13)

- Every number in `docs/SCALE_AND_PERFORMANCE.md` was actually measured
  by running `data_plane.benchmarks.cli` (or the equivalent pytest) in
  this repository's own development environment -- never modeled,
  extrapolated, or estimated. Where a real cluster-scale number cannot
  be honestly produced from `local[*]` (network shuffle cost across
  real nodes, executor-loss recovery, true autoscaling), the report says
  so explicitly instead of guessing.
- `BenchmarkSuiteReport.environment` records the exact machine/PySpark
  version/scale profile every run used, so a number is never presented
  without the context needed to judge whether it would reproduce
  elsewhere.
