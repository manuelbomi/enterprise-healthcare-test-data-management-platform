"""Command-line entry point for synthetic scenario generation.

Usage::

    # Augment an existing (e.g. Phase 4 subsetted-and-masked) estate with
    # scenario records:
    python -m data_plane.synthetic.cli \\
        --base-estate-dir data/tmp/synthetic-estate-subset \\
        --out-dir data/tmp/synthetic-estate-scenarios \\
        --scenario normal_claims --scenario high_cost_claims \\
        --scenario invalid_claim_references

    # Generate a standalone scenario-only dataset (no base estate at all):
    python -m data_plane.synthetic.cli \\
        --out-dir data/tmp/synthetic-scenarios-standalone \\
        --scenario missing_provider --scenario expired_coverage

    # Every one of the eleven required scenarios in one run:
    python -m data_plane.synthetic.cli --out-dir data/tmp/synthetic-scenarios-all --all-scenarios

``--count <scenario>=<n>`` overrides the default instance count for one
scenario (repeatable); see `scenarios.DEFAULT_SCENARIO_COUNTS` for the
defaults.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.synthetic.engine import generate_synthetic_scenarios


def _parse_counts(pairs: list[str]) -> dict[ScenarioType, int]:
    counts: dict[ScenarioType, int] = {}
    for pair in pairs:
        if "=" not in pair:
            raise ValueError(f"--count must be scenario=n, got {pair!r}")
        key, value = pair.split("=", 1)
        counts[ScenarioType(key.strip())] = int(value.strip())
    return counts


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Generate SYNTHETIC/NEGATIVE_TEST scenario records to supplement a masked/subsetted "
            "dataset, or a standalone scenario-only dataset."
        )
    )
    parser.add_argument(
        "--base-estate-dir",
        default=None,
        help=(
            "Directory of an existing estate to augment (e.g. a data_plane.subsetting.cli or "
            "data_plane.masking.cli output). Omit for standalone mode (scenario-only output, "
            "zero MASKED_PRODUCTION_LIKE rows)."
        ),
    )
    parser.add_argument("--out-dir", required=True, help="Output directory for the generated estate + manifest.")
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        choices=sorted(s.value for s in ScenarioType),
        help="Scenario to generate, repeatable.",
    )
    parser.add_argument(
        "--all-scenarios", action="store_true", help="Generate all eleven required scenarios."
    )
    parser.add_argument(
        "--count",
        action="append",
        default=[],
        metavar="SCENARIO=N",
        help="Override the instance count for one scenario, repeatable.",
    )
    parser.add_argument("--seed", type=int, default=90000, help="Random seed (default: 90000).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.all_scenarios:
        scenarios = list(ScenarioType)
    else:
        scenarios = [ScenarioType(s) for s in args.scenario]
    if not scenarios:
        print("Specify at least one --scenario, or --all-scenarios.", file=sys.stderr)
        return 1

    base_estate_dir = Path(args.base_estate_dir) if args.base_estate_dir else None
    if base_estate_dir is not None and not base_estate_dir.exists():
        print(f"Base estate directory '{base_estate_dir}' does not exist.", file=sys.stderr)
        return 1

    try:
        counts = _parse_counts(args.count)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    result = generate_synthetic_scenarios(
        out_dir, scenarios, base_estate_dir=base_estate_dir, counts=counts, seed=args.seed
    )

    manifest = result.manifest
    print(f"Mode: {manifest.mode}" + (f" (base: {manifest.base_estate_dir})" if manifest.base_estate_dir else ""))
    print(f"Output: {out_dir}")
    print("Scenarios generated:")
    for record in manifest.scenarios:
        total = sum(record.row_counts.values())
        print(f"  {record.scenario.value:<36} provenance={record.provenance.value:<16} rows={total}")
    print("Total row counts (entity -> count):")
    for entity, count in sorted(manifest.total_row_counts.items()):
        print(f"  {entity:>20}: {count}")
    print("Provenance row counts:")
    for provenance in DataProvenance:
        print(f"  {provenance.value:<24}: {manifest.provenance_row_counts.get(provenance.value, 0)}")
    print(f"Estimated output storage: {manifest.estimated_output_storage_bytes:,} bytes")
    manifest_path = out_dir / "synthetic_generation_manifest.json"
    print(f"Manifest: {manifest_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
