"""Benchmark tooling for `ROADMAP.md` Phase 14 (Scale and Performance
Engineering): configurable-volume, real measurements of dataset
generation time, masking throughput, subsetting throughput, validation
time, storage footprint, and Parquet compression ratio -- run against a
real, on-disk synthetic estate at a caller-selected
`data_plane.reference_data.scale.ScaleProfile`.

Module map
----------
- `harness.py` -- one `benchmark_*` function per measured operation, each
  reusing the real, already-built Phase 1/3/4/8 engine it measures (or,
  for the two Spark comparison points, the real `data_plane.spark` jobs
  this same phase adds).
- `report.py` -- `run_full_suite` wires every `harness.py` function
  together against one freshly generated estate and returns a
  `BenchmarkSuiteReport`; `write_report` persists it as JSON (and,
  optionally, a rendered Markdown table).
- `cli.py` -- `python -m data_plane.benchmarks.cli --scale performance`.

See `README.md` in this directory and `docs/SCALE_AND_PERFORMANCE.md` for
the real numbers a run in this repository's own development environment
actually produced, and the honesty conventions (never fabricate a
distributed-cluster number) this package follows.
"""

from data_plane.benchmarks.harness import BenchmarkResult
from data_plane.benchmarks.report import BenchmarkSuiteReport, run_full_suite, write_report

__all__ = ["BenchmarkResult", "BenchmarkSuiteReport", "run_full_suite", "write_report"]
