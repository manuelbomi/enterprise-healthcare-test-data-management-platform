"""Command-line entry point for generating the synthetic healthcare estate.

Usage::

    python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
    python -m data_plane.reference_data.cli --scale developer --seed 42
    python -m data_plane.reference_data.cli --scale qa --database-url postgresql+psycopg://tdm:tdm@localhost:5432/tdm_source_enrollment

``--out-dir`` defaults to ``data/tmp/synthetic-estate`` (relative to the
current working directory), which matches the repository's
``.gitignore`` rule for ``data/tmp/`` — generated output is disposable
and is never committed.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES, get_scale_profile


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Generate the SYNTHETIC multi-system healthcare data estate."
    )
    parser.add_argument(
        "--scale",
        choices=sorted(SCALE_PROFILES),
        default="tiny",
        help="Named scale profile (default: tiny).",
    )
    parser.add_argument(
        "--out-dir",
        default="data/tmp/synthetic-estate",
        help="Output directory (default: data/tmp/synthetic-estate).",
    )
    parser.add_argument(
        "--seed", type=int, default=20240101, help="Random seed for reproducible generation."
    )
    parser.add_argument(
        "--database-url",
        default=None,
        help=(
            "Optional PostgreSQL DSN for the enrollment system "
            "(e.g. postgresql+psycopg://tdm:tdm@localhost:5432/tdm_source_enrollment). "
            "Defaults to a local SQLite file under --out-dir."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    profile = get_scale_profile(args.scale)
    generator = EstateGenerator(profile, DEFAULT_EDGE_CASE_CONFIG, seed=args.seed)
    estate = generator.generate()

    written = write_estate(estate, Path(args.out_dir), database_url=args.database_url)

    print(f"Generated '{args.scale}' scale estate (seed={args.seed}).")
    print(f"  Enrollment DB: {written.enrollment_database_url}")
    print(f"  Files written: {len(written.files_written)}")
    print(f"  Manifest:      {written.manifest_path}")
    for entity, count in estate.row_counts().items():
        print(f"    {entity:>20}: {count}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
