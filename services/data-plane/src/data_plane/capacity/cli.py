"""Command-line entry point for real, on-disk footprint measurement.

Usage::

    # Measure a directory's real footprint (compressed bytes, per-extension
    # breakdown, real Parquet-vs-CSV compression ratios):
    python -m data_plane.capacity.cli footprint data/tmp/synthetic-estate

    # Analyze the real Hive-style partition layout of a dataset directory:
    python -m data_plane.capacity.cli partitions \\
        data/tmp/synthetic-estate/object_storage_claims_parquet/claims-warehouse/claim

This is a measurement tool, not a pipeline stage -- it reads whatever
directory it's pointed at (the output of `data_plane.reference_data`,
`data_plane.certification`, or any other stage) and reports real numbers
about it. It does not write anything back to that directory.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from data_plane.capacity.footprint import measure_directory_footprint
from data_plane.capacity.partitioning import analyze_partitions


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Real, on-disk storage footprint measurement.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    footprint_parser = subparsers.add_parser("footprint", help="Measure a directory's real footprint.")
    footprint_parser.add_argument("path", help="Directory to measure.")

    partitions_parser = subparsers.add_parser("partitions", help="Analyze a directory's real partition layout.")
    partitions_parser.add_argument("path", help="Directory to analyze.")

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    path = Path(args.path)

    if args.command == "footprint":
        report = measure_directory_footprint(path)
        print(f"Root: {report.root_path}")
        print(f"Total: {report.total_bytes:,} bytes across {report.total_file_count} file(s)")
        print("By extension:")
        for ext, size in sorted(report.bytes_by_extension.items(), key=lambda kv: -kv[1]):
            count = report.file_count_by_extension.get(ext, 0)
            print(f"  {ext:>10}: {size:>12,} bytes ({count} file(s))")
        if report.parquet_compression:
            print("Parquet compression (compressed on-disk vs. re-encoded CSV):")
            for m in report.parquet_compression:
                print(
                    f"  {m.source_path}: {m.compressed_bytes:,} bytes compressed, "
                    f"{m.uncompressed_estimate_bytes:,} bytes as CSV "
                    f"({m.compression_ratio:.2f}x smaller), {m.row_count} rows"
                )
            overall = report.overall_parquet_compression_ratio
            if overall is not None:
                print(f"  Overall Parquet compression ratio: {overall:.2f}x")
        return 0

    if args.command == "partitions":
        summary = analyze_partitions(path)
        if summary.partition_key is None:
            print(f"{summary.root_path}: no Hive-style partitions found.")
            return 0
        print(f"Root: {summary.root_path}")
        print(f"Partition key: {summary.partition_key}  ({summary.partition_count} partition(s))")
        for value, size in sorted(summary.bytes_by_partition.items()):
            count = summary.file_count_by_partition.get(value, 0)
            print(f"  {summary.partition_key}={value}: {size:,} bytes ({count} file(s))")
        return 0

    return 1  # pragma: no cover -- argparse's `required=True` makes this unreachable


if __name__ == "__main__":
    sys.exit(main())
