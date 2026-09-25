"""Real benchmark measurements against real, generated synthetic data
(Phase 14) -- every function in this module runs the real pipeline stage
it names and reports real wall-clock numbers from *this* run, never a
fabricated or extrapolated figure. See `docs/SCALE_AND_PERFORMANCE.md`
for the numbers a real run in this repository's own development
environment actually produced, and this package's `README.md` for the
honesty conventions this module follows (the same ones
`docs/CAPACITY_COST_TRADEOFFS.md` and `docs/COMPLIANCE_EVIDENCE.md`
already established for Phase 8/13).

This module deliberately reuses every real engine already built in
earlier phases rather than reimplementing measurement logic a second
time:

- `data_plane.reference_data` (Phase 1) for dataset generation, at a
  caller-selected `ScaleProfile` -- this phase does not build a second
  synthetic-data generator (see `ROADMAP.md` Phase 14's own guidance and
  `problems_phase_14.md`).
- `data_plane.masking.dataset_masker`/`validation` (Phase 3) for the
  pandas-engine masking + validation baseline.
- `data_plane.subsetting.engine` (Phase 4) for the pandas-engine
  subsetting baseline.
- `data_plane.capacity.footprint` (Phase 8) for real on-disk storage
  footprint and Parquet compression-ratio measurement.
- `data_plane.spark.masking_job`/`subsetting_job` (Phase 14, this same
  phase) for the Spark-side comparison.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, TypeVar

from healthcare_tdm_contracts import CatalogEntry, SubsettingStrategy

from data_plane.capacity.footprint import measure_directory_footprint
from data_plane.masking.dataset_masker import MaskingRunReport, mask_estate
from data_plane.masking.engine import MaskingEngine
from data_plane.masking.validation import ValidationReport, validate_masking_run
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import WrittenEstate, write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import get_scale_profile
from data_plane.subsetting.engine import SubsettingRunResult, run_subsetting

T = TypeVar("T")


@dataclass
class BenchmarkResult:
    """One measured operation: a name, a row count, a wall-clock
    duration, and whatever operation-specific numbers matter (bytes,
    compression ratio, file counts, ...). This is the one shape every
    `benchmark_*` function in this module returns (alongside the real
    result object the underlying engine call itself produced), so
    `report.py` can render an arbitrary list of them uniformly.
    """

    name: str
    rows: int
    elapsed_seconds: float
    extra: dict[str, Any] = field(default_factory=dict)

    def records_per_second(self) -> float:
        return self.rows / self.elapsed_seconds if self.elapsed_seconds > 0 else 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "rows": self.rows,
            "elapsed_seconds": round(self.elapsed_seconds, 4),
            "records_per_second": round(self.records_per_second(), 2),
            "extra": self.extra,
        }


def _time(name: str, fn: Callable[[], T], *, rows_of: Callable[[T], int]) -> tuple[T, BenchmarkResult]:
    """Time one call to `fn`, deriving the row count for the resulting
    `BenchmarkResult` from `rows_of(result)`. The one place `time.perf_counter`
    is called in this module, so every benchmark function below measures
    consistently.
    """

    start = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - start
    return result, BenchmarkResult(name=name, rows=rows_of(result), elapsed_seconds=elapsed)


# ---------------------------------------------------------------------------
# Dataset generation
# ---------------------------------------------------------------------------


def benchmark_dataset_generation(
    scale_name: str, out_dir: Path, *, seed: int = 20240101
) -> tuple[WrittenEstate, BenchmarkResult]:
    """Time Phase 1's real `EstateGenerator.generate()` + `write_estate()`
    for `scale_name` (`tiny`/`developer`/`qa`/`performance`) -- the real
    "dataset generation time" metric `ROADMAP.md` Phase 14 asks for.
    """

    profile = get_scale_profile(scale_name)
    total_rows = 0

    def _run() -> WrittenEstate:
        nonlocal total_rows
        generator = EstateGenerator(profile, DEFAULT_EDGE_CASE_CONFIG, seed=seed)
        estate = generator.generate()
        total_rows = sum(estate.row_counts().values())
        return write_estate(estate, out_dir)

    written, benchmark = _time(
        f"dataset_generation[{scale_name}]", _run, rows_of=lambda _: total_rows
    )
    benchmark.extra["scale_profile"] = scale_name
    benchmark.extra["approx_total_rows_estimate"] = profile.approx_total_rows()
    benchmark.extra["files_written"] = len(written.files_written)
    return written, benchmark


# ---------------------------------------------------------------------------
# Storage footprint / compression ratio
# ---------------------------------------------------------------------------


def benchmark_storage_footprint(root: Path, *, name: str = "storage_footprint") -> BenchmarkResult:
    """Real, on-disk footprint measurement (reuses Phase 8's
    `measure_directory_footprint` unmodified) for `root`. Not a
    throughput metric (there is no "operation" to time beyond the
    filesystem walk itself) -- `rows` is the total file count, and
    `extra` carries total bytes, the per-extension breakdown, and the
    mean real Parquet compression ratio actually measured.
    """

    start = time.perf_counter()
    report = measure_directory_footprint(root)
    elapsed = time.perf_counter() - start

    ratios = [m.compression_ratio for m in report.parquet_compression]
    mean_ratio = sum(ratios) / len(ratios) if ratios else None

    return BenchmarkResult(
        name=name,
        rows=report.total_file_count,
        elapsed_seconds=elapsed,
        extra={
            "total_bytes": report.total_bytes,
            "bytes_by_extension": report.bytes_by_extension,
            "file_count_by_extension": report.file_count_by_extension,
            "parquet_files_measured": len(report.parquet_compression),
            "mean_parquet_compression_ratio": mean_ratio,
        },
    )


# ---------------------------------------------------------------------------
# Pandas-engine masking (Phase 3) + validation
# ---------------------------------------------------------------------------


def benchmark_pandas_masking(
    estate_root: Path,
    catalog_entries: list[CatalogEntry],
    out_root: Path,
    *,
    key: bytes,
) -> tuple[MaskingRunReport, BenchmarkResult]:
    """Time Phase 3's real, row-by-row `mask_estate` against a real,
    on-disk estate -- the pandas/row-loop baseline
    `data_plane.spark.masking_job.run_claims_masking_job`'s Spark
    `pandas_udf` implementation is compared against in
    `docs/SCALE_AND_PERFORMANCE.md`.
    """

    engine = MaskingEngine(key=key)

    def _run() -> MaskingRunReport:
        return mask_estate(estate_root, catalog_entries, out_root, engine)

    report, benchmark = _time(
        "pandas_masking[full_estate]", _run, rows_of=lambda r: r.rows_processed
    )
    benchmark.extra["columns_masked"] = report.columns_masked
    benchmark.extra["technique_counts"] = report.technique_counts
    return report, benchmark


def benchmark_pandas_masking_validation(
    report: MaskingRunReport,
) -> tuple[ValidationReport, BenchmarkResult]:
    """Time Phase 3's real `validate_masking_run` against a real masking
    run's linkage samples -- the "validation time" metric.
    """

    def _run() -> ValidationReport:
        return validate_masking_run(linkage_samples=report.linkage_samples)

    validation, benchmark = _time(
        "pandas_masking_validation",
        _run,
        rows_of=lambda v: sum(len(s) for s in report.linkage_samples.values()),
    )
    benchmark.extra["checks_run"] = validation.checks_run
    benchmark.extra["passed"] = validation.passed
    return validation, benchmark


# ---------------------------------------------------------------------------
# Pandas-engine subsetting (Phase 4)
# ---------------------------------------------------------------------------


def benchmark_pandas_subsetting(
    estate_root: Path, out_root: Path, *, percentage: float = 2.0, seed: int = 20240101
) -> tuple[SubsettingRunResult, BenchmarkResult]:
    """Time Phase 4's real, pandas/graph-walk `run_subsetting` -- the
    baseline `data_plane.spark.subsetting_job.run_member_subsetting_job`'s
    broadcast-join implementation is compared against.
    """

    def _run() -> SubsettingRunResult:
        return run_subsetting(
            estate_root,
            out_root,
            SubsettingStrategy.PERCENTAGE,
            {"percentage": str(percentage), "seed": str(seed)},
        )

    result, benchmark = _time(
        f"pandas_subsetting[{percentage}pct]",
        _run,
        rows_of=lambda r: r.manifest.selected_counts.get("claim", 0)
        + r.manifest.selected_counts.get("claim_line", 0),
    )
    benchmark.extra["selected_member_count"] = result.manifest.selected_counts.get("member", 0)
    benchmark.extra["source_member_count"] = result.manifest.source_counts.get("member", 0)
    return result, benchmark


def build_catalog_for_estate(estate_root: Path) -> list[CatalogEntry]:
    """Run real Phase 2 discovery against a real, on-disk estate and
    return its catalog -- the exact `scan_estate` -> `build_catalog`
    sequence `tests/masking/test_dataset_masker_against_real_estate.py`
    already established, extracted here as a shared helper so this
    module and `report.run_full_suite` do not duplicate it.
    """

    from data_plane.discovery.catalog_builder import build_catalog
    from data_plane.discovery.engine import ClassificationEngine
    from data_plane.discovery.scanner import scan_estate

    columns = scan_estate(estate_root)
    return build_catalog(columns, ClassificationEngine())


# ---------------------------------------------------------------------------
# Spark-engine masking/subsetting (Phase 14) -- the horizontal-scaling
# comparison point for the two pandas-engine benchmarks above.
# ---------------------------------------------------------------------------


def benchmark_spark_masking(
    spark: Any,
    input_root: Path,
    output_root: Path,
    *,
    key: bytes,
    status_filter: str | None = None,
) -> tuple[Any, BenchmarkResult]:
    """Time `data_plane.spark.masking_job.run_claims_masking_job` -- the
    Spark `pandas_udf` comparison point for `benchmark_pandas_masking`.
    `spark` is a `pyspark.sql.SparkSession` (typed `Any` here so this
    module has no hard import-time dependency on `pyspark` for callers
    that only want the pandas-engine benchmarks).
    """

    from data_plane.spark.masking_job import run_claims_masking_job

    def _run() -> Any:
        return run_claims_masking_job(
            spark, str(input_root), str(output_root), key=key, status_filter=status_filter
        )

    result, benchmark = _time(
        "spark_masking[claim]", _run, rows_of=lambda r: r.rows_written
    )
    benchmark.extra["columns_masked"] = result.columns_masked
    benchmark.extra["read_elapsed_seconds"] = round(result.read_elapsed_seconds, 4)
    benchmark.extra["write_elapsed_seconds"] = round(result.write_elapsed_seconds, 4)
    return result, benchmark


def benchmark_spark_subsetting(
    spark: Any,
    input_root: Path,
    output_root: Path,
    *,
    member_fraction: float = 0.02,
    seed: int = 20240101,
) -> tuple[Any, BenchmarkResult]:
    """Time `data_plane.spark.subsetting_job.run_member_subsetting_job` --
    the broadcast-join comparison point for `benchmark_pandas_subsetting`.
    """

    from data_plane.spark.subsetting_job import run_member_subsetting_job

    def _run() -> Any:
        return run_member_subsetting_job(
            spark, str(input_root), str(output_root), member_fraction=member_fraction, seed=seed
        )

    result, benchmark = _time(
        f"spark_subsetting[{member_fraction}]",
        _run,
        rows_of=lambda r: r.claims_output_rows + r.claim_lines_output_rows,
    )
    benchmark.extra["members_sampled"] = result.members_sampled
    benchmark.extra["claims_input_rows"] = result.claims_input_rows
    benchmark.extra["claims_output_rows"] = result.claims_output_rows
    benchmark.extra["claim_lines_input_rows"] = result.claim_lines_input_rows
    benchmark.extra["claim_lines_output_rows"] = result.claim_lines_output_rows
    benchmark.extra["selectivity"] = round(result.selectivity(), 4)
    return result, benchmark


__all__ = [
    "BenchmarkResult",
    "benchmark_dataset_generation",
    "benchmark_pandas_masking",
    "benchmark_pandas_masking_validation",
    "benchmark_pandas_subsetting",
    "benchmark_spark_masking",
    "benchmark_spark_subsetting",
    "benchmark_storage_footprint",
    "build_catalog_for_estate",
]
