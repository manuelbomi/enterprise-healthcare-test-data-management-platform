"""Command-line entry point for subsetting a generated synthetic estate.

Usage::

    # 1. Generate an estate (Phase 1 CLI) if you don't already have one:
    python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

    # 2. Subset it, e.g. a fixed population of 8 members:
    python -m data_plane.subsetting.cli --estate-dir data/tmp/synthetic-estate \\
        --out-dir data/tmp/synthetic-estate-subset \\
        --strategy fixed_population --param count=8

Every strategy takes its parameters via one or more repeated
``--param key=value`` flags:

- ``percentage``:      ``--param percentage=20`` (percent, 0-100)
- ``fixed_population``: ``--param count=8``
- ``stratified``:       ``--param strata_field=gender --param per_stratum=4``
- ``date_window``:      ``--param start_date=2025-01-01 --param end_date=2025-03-31``
- ``business_rule``:    ``--param coverage_status=active --param claim_status=paid --param min_matching_claims=1``
- ``risk_edge_case``:   ``--param max_members=10`` (optional; omit for the full risk pool)

``--param seed=<int>`` is accepted by every strategy that samples
randomly (default: 20240101, matching the generator's own default).

``--negative-test`` intentionally injects a dangling ``claim.provider_id``
reference into the output, for exercising negative-test / edge-case
handling downstream -- see `negative_testing.py`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from healthcare_tdm_contracts import SubsettingStrategy

from data_plane.subsetting.engine import run_subsetting


def _parse_params(pairs: list[str]) -> dict[str, str]:
    params: dict[str, str] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--param must be key=value, got {pair!r}")
        key, value = pair.split("=", 1)
        params[key.strip()] = value.strip()
    return params


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Select a referentially closed subset of the SYNTHETIC multi-system healthcare estate."
    )
    parser.add_argument("--estate-dir", required=True, help="Output directory of a reference_data.cli run.")
    parser.add_argument(
        "--out-dir", required=True, help="Output directory for the subset estate + subset_manifest.json."
    )
    parser.add_argument(
        "--strategy",
        required=True,
        choices=sorted(s.value for s in SubsettingStrategy),
        help="Which of the six population-selection strategies to run.",
    )
    parser.add_argument(
        "--param",
        action="append",
        default=[],
        metavar="KEY=VALUE",
        help="Strategy parameter, repeatable (see module docstring for each strategy's parameters).",
    )
    parser.add_argument(
        "--negative-test",
        action="store_true",
        help="Intentionally inject a dangling claim.provider_id reference for negative testing.",
    )
    parser.add_argument(
        "--negative-test-count",
        type=int,
        default=1,
        help=(
            "How many Provider rows to remove when --negative-test is set (default: 1); each "
            "removed provider breaks every selected claim that references it, so the resulting "
            "dangling-reference count can be larger than this number."
        ),
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    estate_dir = Path(args.estate_dir)
    if not estate_dir.exists():
        print(
            f"Estate directory '{estate_dir}' does not exist. Generate one first with "
            f"'python -m data_plane.reference_data.cli --scale tiny --out-dir {estate_dir}'.",
            file=sys.stderr,
        )
        return 1

    try:
        parameters = _parse_params(args.param)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    strategy = SubsettingStrategy(args.strategy)
    out_dir = Path(args.out_dir)

    try:
        result = run_subsetting(
            estate_dir,
            out_dir,
            strategy,
            parameters,
            negative_test=args.negative_test,
            negative_test_count=args.negative_test_count,
        )
    except (KeyError, ValueError) as exc:
        print(f"Invalid strategy parameters: {exc}", file=sys.stderr)
        return 1

    manifest = result.manifest
    print(f"Strategy: {strategy.value} -- {manifest.selection.description}")
    print(f"Subset written: {out_dir}")
    print("Row counts (source -> selected):")
    for entity, source_count in sorted(manifest.source_counts.items()):
        selected_count = manifest.selected_counts.get(entity, 0)
        print(f"  {entity:>20}: {source_count:>7} -> {selected_count}")
    print("Relationship edges traversed:")
    for edge in manifest.relationship_edges:
        print(f"  {edge.parent_entity} -> {edge.child_entity}: {edge.edge_count}")
    print(
        f"Estimated storage: source={manifest.estimated_source_storage_bytes:,} bytes, "
        f"subset={manifest.estimated_subset_storage_bytes:,} bytes"
    )
    print(f"Integrity status: {manifest.integrity_status.value}")
    for line in manifest.integrity_findings:
        print(f"  {line}")

    manifest_path = out_dir / "subset_manifest.json"
    print(f"Manifest: {manifest_path}")

    return 0 if result.validation.passed else 2


if __name__ == "__main__":
    sys.exit(main())
