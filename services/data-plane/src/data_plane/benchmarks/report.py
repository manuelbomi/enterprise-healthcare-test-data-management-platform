"""Assemble and render a `BenchmarkSuiteReport` -- the structured record
`docs/SCALE_AND_PERFORMANCE.md` is written from, and what
`data_plane.benchmarks.cli` / `scripts/demo_phase14_benchmarks.py` write
to disk as JSON.

`run_full_suite` is the one function that runs *every* Phase 14 metric
end to end against one real, generated estate: dataset generation time,
pandas-vs-Spark masking throughput, pandas-vs-Spark subsetting
throughput, validation time, storage footprint, and compression ratio.
It reuses every `benchmark_*` function in `harness.py` -- it does not
duplicate any measurement logic.
"""

from __future__ import annotations

import json
import platform
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from data_plane.benchmarks.harness import (
    BenchmarkResult,
    benchmark_dataset_generation,
    benchmark_pandas_masking,
    benchmark_pandas_masking_validation,
    benchmark_pandas_subsetting,
    benchmark_spark_masking,
    benchmark_spark_subsetting,
    benchmark_storage_footprint,
    build_catalog_for_estate,
)
from data_plane.masking.secrets import resolve_hmac_key


@dataclass
class BenchmarkSuiteReport:
    """Every `BenchmarkResult` from one `run_full_suite` call, plus the
    environment metadata needed to interpret them honestly (this machine,
    this Python/PySpark version, `local[*]` -- never a real cluster; see
    `data_plane.spark.session`'s module docstring).
    """

    generated_at: str
    scale_profile: str
    environment: dict[str, Any]
    results: list[BenchmarkResult] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "generated_at": self.generated_at,
            "scale_profile": self.scale_profile,
            "environment": self.environment,
            "results": [r.to_dict() for r in self.results],
            "notes": self.notes,
        }

    def to_markdown(self) -> str:
        lines = [
            f"Generated: {self.generated_at}",
            f"Scale profile: `{self.scale_profile}`",
            "",
            "Environment:",
            "",
        ]
        for key, value in self.environment.items():
            lines.append(f"- **{key}**: {value}")
        lines.append("")
        lines.append("| Operation | Rows | Elapsed (s) | Records/sec | Notes |")
        lines.append("|---|---|---|---|---|")
        for r in self.results:
            note_bits = []
            for k in ("mean_parquet_compression_ratio", "selectivity", "passed"):
                if k in r.extra and r.extra[k] is not None:
                    note_bits.append(f"{k}={r.extra[k]}")
            note = "; ".join(note_bits)
            lines.append(
                f"| `{r.name}` | {r.rows:,} | {r.elapsed_seconds:.3f} | "
                f"{r.records_per_second():,.0f} | {note} |"
            )
        if self.notes:
            lines.append("")
            lines.append("Notes:")
            for n in self.notes:
                lines.append(f"- {n}")
        return "\n".join(lines)


def _environment_metadata(scale_profile: str) -> dict[str, Any]:
    import pyspark

    return {
        "platform": platform.platform(),
        "python_version": sys.version.split()[0],
        "cpu_count": __import__("os").cpu_count(),
        "pyspark_version": pyspark.__version__,
        "spark_master": "local[*] (no real cluster in this repository's infrastructure)",
        "scale_profile": scale_profile,
    }


def run_full_suite(
    scale_name: str,
    work_dir: Path,
    *,
    seed: int = 20240101,
    member_fraction_pct: float = 2.0,
    key: bytes | None = None,
) -> BenchmarkSuiteReport:
    """Run every Phase 14 benchmark end to end against one freshly
    generated estate at `scale_name`, under `work_dir` (caller owns
    cleanup -- this is disposable, like every other `data/tmp/` output in
    this repository).
    """

    from data_plane.spark.session import get_local_spark_session, stop_spark_session

    key = key if key is not None else resolve_hmac_key()

    estate_root = work_dir / "estate"
    pandas_masked_root = work_dir / "pandas-masked"
    pandas_subset_root = work_dir / "pandas-subset"
    spark_masked_root = work_dir / "spark-masked"
    spark_subset_root = work_dir / "spark-subset"

    results: list[BenchmarkResult] = []

    written, generation_bm = benchmark_dataset_generation(scale_name, estate_root, seed=seed)
    results.append(generation_bm)

    raw_footprint_bm = benchmark_storage_footprint(estate_root, name="storage_footprint[raw_estate]")
    results.append(raw_footprint_bm)

    catalog_entries = build_catalog_for_estate(estate_root)

    masking_report, pandas_masking_bm = benchmark_pandas_masking(
        estate_root, catalog_entries, pandas_masked_root, key=key
    )
    results.append(pandas_masking_bm)

    _validation, validation_bm = benchmark_pandas_masking_validation(masking_report)
    results.append(validation_bm)

    _subset_result, pandas_subsetting_bm = benchmark_pandas_subsetting(
        estate_root, pandas_subset_root, percentage=member_fraction_pct, seed=seed
    )
    results.append(pandas_subsetting_bm)

    claims_warehouse_root = estate_root / "object_storage_claims_parquet" / "claims-warehouse"
    spark = get_local_spark_session("data_plane.benchmarks")
    try:
        _spark_mask_result, spark_masking_bm = benchmark_spark_masking(
            spark, claims_warehouse_root, spark_masked_root, key=key
        )
        results.append(spark_masking_bm)

        _spark_subset_result, spark_subsetting_bm = benchmark_spark_subsetting(
            spark,
            claims_warehouse_root,
            spark_subset_root,
            member_fraction=member_fraction_pct / 100.0,
            seed=seed,
        )
        results.append(spark_subsetting_bm)
    finally:
        stop_spark_session(spark)

    masked_footprint_bm = benchmark_storage_footprint(
        pandas_masked_root, name="storage_footprint[pandas_masked]"
    )
    results.append(masked_footprint_bm)

    notes = [
        "Every `spark_*` result ran against SparkSession.builder.master('local[*]') "
        "-- one JVM process on the machine that generated this report, not a "
        "distributed cluster. See data_plane/spark/README.md.",
        "pandas_masking and spark_masking mask different (but overlapping) sets of "
        "columns -- see data_plane/spark/masking_job.py's DEFAULT_MASKED_COLUMNS -- "
        "so their 'rows' counts are comparable but their absolute elapsed times "
        "reflect different total work, not a pure apples-to-apples technique-for-"
        "technique race. docs/SCALE_AND_PERFORMANCE.md discusses this explicitly.",
    ]

    return BenchmarkSuiteReport(
        generated_at=datetime.now(timezone.utc).isoformat(),
        scale_profile=scale_name,
        environment=_environment_metadata(scale_name),
        results=results,
        notes=notes,
    )


def write_report(report: BenchmarkSuiteReport, *, json_path: Path, markdown_path: Path | None = None) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(report.to_dict(), indent=2), encoding="utf-8")
    if markdown_path is not None:
        markdown_path.parent.mkdir(parents=True, exist_ok=True)
        markdown_path.write_text(report.to_markdown(), encoding="utf-8")


__all__ = ["BenchmarkSuiteReport", "run_full_suite", "write_report"]
