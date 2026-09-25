"""Command-line entry point for running the full Phase 14 benchmark suite
and writing a JSON + Markdown report.

Usage::

    python -m data_plane.benchmarks.cli --scale qa --out-dir data/tmp/phase14-benchmarks

Requires `TDM_MASKING_HMAC_KEY` to be set (or a `.env` -- see
`data_plane.masking.secrets`), exactly like `data_plane.masking.cli`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_plane.benchmarks.report import run_full_suite, write_report


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the full Phase 14 benchmark suite against a freshly generated estate."
    )
    parser.add_argument(
        "--scale",
        default="qa",
        help="Named scale profile to generate and benchmark against (default: qa).",
    )
    parser.add_argument(
        "--out-dir",
        default="data/tmp/phase14-benchmarks",
        help="Working directory for the generated estate and job outputs (disposable).",
    )
    parser.add_argument(
        "--report-dir",
        default="data/tmp/phase14-benchmarks",
        help="Where to write benchmark_report.json/.md.",
    )
    parser.add_argument("--seed", type=int, default=20240101)
    parser.add_argument("--member-fraction-pct", type=float, default=2.0)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = run_full_suite(
        args.scale,
        Path(args.out_dir),
        seed=args.seed,
        member_fraction_pct=args.member_fraction_pct,
    )
    report_dir = Path(args.report_dir)
    write_report(
        report,
        json_path=report_dir / "benchmark_report.json",
        markdown_path=report_dir / "benchmark_report.md",
    )
    print(report.to_markdown())
    print(f"\nWrote {report_dir / 'benchmark_report.json'}")
    print(f"Wrote {report_dir / 'benchmark_report.md'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
