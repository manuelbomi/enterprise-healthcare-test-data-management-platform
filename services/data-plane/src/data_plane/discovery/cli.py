"""Command-line entry point for running discovery against a generated
synthetic estate.

Usage::

    # 1. Generate an estate (Phase 1 CLI) if you don't already have one:
    python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

    # 2. Run discovery against it:
    python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \\
        --out data/tmp/synthetic-estate/catalog.json

``--out`` defaults to ``<estate-dir>/catalog.json``, matching the
repository's ``.gitignore`` rule for ``data/tmp/`` — generated catalogs
are disposable and reproducible from the estate + this engine, never
committed. Point the control plane's ``TDM_CONTROL_PLANE_CATALOG_PATH``
at this file's location to serve it over the catalog API (see
``docs/adr/0009-catalog-artifact-handoff.md``).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from data_plane.discovery.catalog_builder import build_catalog, write_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Classify PHI/PII across the SYNTHETIC multi-system healthcare estate."
    )
    parser.add_argument(
        "--estate-dir",
        required=True,
        help="Output directory a data_plane.reference_data.cli run was written to.",
    )
    parser.add_argument(
        "--out",
        default=None,
        help="Output path for the catalog.json artifact (default: <estate-dir>/catalog.json).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    estate_dir = Path(args.estate_dir)
    if not estate_dir.exists():
        print(
            f"Estate directory '{estate_dir}' does not exist. Generate one first with "
            "'python -m data_plane.reference_data.cli --scale tiny --out-dir "
            f"{estate_dir}'.",
            file=sys.stderr,
        )
        return 1

    out_path = Path(args.out) if args.out else estate_dir / "catalog.json"

    columns = scan_estate(estate_dir)
    if not columns:
        print(f"No columns discovered under '{estate_dir}' — is this a valid estate output dir?", file=sys.stderr)
        return 1

    engine = ClassificationEngine()
    entries = build_catalog(columns, engine)
    write_catalog(entries, out_path)

    by_category: dict[str, int] = {}
    needs_review = 0
    for entry in entries:
        category = entry.classification.category.value if entry.classification.category else "unknown"
        by_category[category] = by_category.get(category, 0) + 1
        if entry.classification.needs_review:
            needs_review += 1

    print(f"Scanned {len(columns)} columns across {len({c.source_system for c in columns})} source systems.")
    print(f"Catalog written: {out_path}")
    print("By category:")
    for category, count in sorted(by_category.items()):
        print(f"  {category:>18}: {count}")
    print(f"Flagged for steward review (confidence < {0.7:.1f}, unconfirmed): {needs_review}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
