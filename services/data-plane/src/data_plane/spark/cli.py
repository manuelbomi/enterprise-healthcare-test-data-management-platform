"""Command-line entry point for running the Phase 14 PySpark jobs
directly against a real, on-disk estate (e.g. one
`data_plane.reference_data.cli` already generated).

Usage::

    python -m data_plane.spark.cli mask \\
        --input-root data/tmp/synthetic-estate/object_storage_claims_parquet/claims-warehouse \\
        --output-root data/tmp/spark-masked-claims

    python -m data_plane.spark.cli subset \\
        --input-root data/tmp/synthetic-estate/object_storage_claims_parquet/claims-warehouse \\
        --output-root data/tmp/spark-subset-claims \\
        --member-fraction 0.02

Mirrors the shape of `data_plane.masking.cli`/`data_plane.subsetting.cli`
(one CLI per engine), except this one has two subcommands instead of a
separate module each, since both jobs are small and share the same
`SparkSession` setup story.
"""

from __future__ import annotations

import argparse
import sys

from data_plane.masking.secrets import resolve_hmac_key
from data_plane.spark.masking_job import run_claims_masking_job
from data_plane.spark.session import get_local_spark_session, stop_spark_session
from data_plane.spark.subsetting_job import run_member_subsetting_job


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run a Phase 14 PySpark job against a real, on-disk claims-warehouse extract."
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    mask_parser = subparsers.add_parser("mask", help="Mask claim identifiers with pandas_udf.")
    mask_parser.add_argument("--input-root", required=True)
    mask_parser.add_argument("--output-root", required=True)
    mask_parser.add_argument("--status-filter", default=None)

    subset_parser = subparsers.add_parser(
        "subset", help="Select a member fraction via broadcast join."
    )
    subset_parser.add_argument("--input-root", required=True)
    subset_parser.add_argument("--output-root", required=True)
    subset_parser.add_argument("--member-fraction", type=float, default=0.02)
    subset_parser.add_argument("--seed", type=int, default=20240101)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    spark = get_local_spark_session(f"data_plane.spark.cli:{args.command}")
    try:
        if args.command == "mask":
            key = resolve_hmac_key()
            mask_result = run_claims_masking_job(
                spark,
                args.input_root,
                args.output_root,
                key=key,
                status_filter=args.status_filter,
            )
            print(
                f"Masked {mask_result.rows_written} claim rows in "
                f"{mask_result.elapsed_seconds:.2f}s"
            )
            print(f"  columns masked: {mask_result.columns_masked}")
            print(f"  records/sec:    {mask_result.records_per_second():.0f}")
        elif args.command == "subset":
            subset_result = run_member_subsetting_job(
                spark,
                args.input_root,
                args.output_root,
                member_fraction=args.member_fraction,
                seed=args.seed,
            )
            print(
                f"Selected {subset_result.members_sampled} members in "
                f"{subset_result.elapsed_seconds:.2f}s"
            )
            print(
                f"  claims:      {subset_result.claims_input_rows} -> "
                f"{subset_result.claims_output_rows}"
            )
            print(
                f"  claim lines: {subset_result.claim_lines_input_rows} -> "
                f"{subset_result.claim_lines_output_rows}"
            )
            print(f"  selectivity: {subset_result.selectivity():.4f}")
        return 0
    finally:
        stop_spark_session(spark)


if __name__ == "__main__":
    sys.exit(main())
