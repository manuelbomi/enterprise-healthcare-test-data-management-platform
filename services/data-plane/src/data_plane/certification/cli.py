"""Command-line entry point for the end-to-end certification pipeline.

Usage::

    # Generate a fresh tiny-scale estate and certify a fixed_population subset of it:
    python -m data_plane.certification.cli --scale tiny --out-dir data/tmp/certification-run \\
        --strategy fixed_population --param count=10

    # Certify an existing estate instead of generating a new one:
    python -m data_plane.certification.cli --estate-dir data/tmp/synthetic-estate \\
        --out-dir data/tmp/certification-run --strategy percentage --param percentage=20

    # Also generate optional synthetic scenarios before certifying, and publish on success:
    python -m data_plane.certification.cli --out-dir data/tmp/certification-run \\
        --strategy fixed_population --param count=10 \\
        --scenario high_cost_claims --scenario invalid_claim_references --publish

A masking key is required (see `data_plane.masking.secrets` /
`--generate-dev-key` below); an integrity-signing key is optional but
strongly recommended (`--generate-dev-key` generates one of each).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from healthcare_tdm_contracts import ScenarioType, SubsettingStrategy

from data_plane.certification import signing as certification_signing
from data_plane.certification.pipeline import run_certification_pipeline
from data_plane.masking import secrets as masking_secrets


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
        description="Run the full INGEST -> ... -> CERTIFY (-> PUBLISH) certification pipeline."
    )
    parser.add_argument(
        "--generate-dev-key",
        action="store_true",
        help="Print a fresh masking key and certification signing key for LOCAL DEV/TEST ONLY, then exit.",
    )
    parser.add_argument("--estate-dir", default=None, help="Reuse an existing estate instead of generating one.")
    parser.add_argument("--scale", default="tiny", help="Scale profile to generate if --estate-dir is omitted.")
    parser.add_argument("--seed", type=int, default=20240101)
    parser.add_argument("--out-dir", required=False, default=None, help="Output directory for this run.")
    parser.add_argument(
        "--strategy",
        default="fixed_population",
        choices=sorted(s.value for s in SubsettingStrategy),
    )
    parser.add_argument("--param", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument(
        "--scenario",
        action="append",
        default=[],
        choices=sorted(s.value for s in ScenarioType),
        help="Optional synthetic scenario(s) to generate on top of the masked subset. Repeatable.",
    )
    parser.add_argument("--strict-orphans", action="store_true")
    parser.add_argument("--max-allowed-orphans", type=int, default=None)
    parser.add_argument("--publish", action="store_true", help="Publish automatically if certification succeeds.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.generate_dev_key:
        print("Generated LOCAL DEV/TEST-ONLY keys (never written to disk, never the same twice):\n")
        print(f"  {masking_secrets.ENV_VAR}={masking_secrets.generate_dev_key()}")
        print(f"  {certification_signing.ENV_VAR}={certification_signing.generate_dev_key()}\n")
        print("Export both for this shell session, or paste them into a gitignored .env file.")
        return 0

    if not args.out_dir:
        print("--out-dir is required unless --generate-dev-key is set.", file=sys.stderr)
        return 1

    try:
        parameters = _parse_params(args.param)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    try:
        masking_key = masking_secrets.resolve_hmac_key()
    except (masking_secrets.MissingMaskingKeyError, masking_secrets.WeakMaskingKeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    signing_key: bytes | None
    try:
        signing_key = certification_signing.resolve_signing_key()
    except (
        certification_signing.MissingCertificationKeyError,
        certification_signing.WeakCertificationKeyError,
    ) as exc:
        print(f"Warning: {exc}\nProceeding with an UNSIGNED report.", file=sys.stderr)
        signing_key = None

    estate_dir = Path(args.estate_dir) if args.estate_dir else None
    out_dir = Path(args.out_dir)
    scenarios = [ScenarioType(s) for s in args.scenario] or None

    result = run_certification_pipeline(
        out_dir,
        estate_dir=estate_dir,
        scale=args.scale,
        seed=args.seed,
        subset_strategy=SubsettingStrategy(args.strategy),
        subset_parameters=parameters,
        masking_key=masking_key,
        synthetic_scenarios=scenarios,
        strict_orphans=args.strict_orphans,
        max_allowed_orphans=args.max_allowed_orphans,
        signing_key=signing_key,
        auto_publish=args.publish,
    )

    report = result.report
    print(f"Certification report: {result.report_path}")
    print(f"Dataset: {report.dataset_name}  Status: {report.status.value.upper()}")
    print(f"Masking policy: {report.masking_policy_name} v{report.masking_policy_version}")
    print(f"Masking engine version: {report.masking_engine_version}")
    print("Gates:")
    for gate in report.gates:
        mark = "PASS" if gate.passed else "FAIL"
        print(f"  [{mark}] {gate.gate.value}: {gate.detail}")
    print("Row count reconciliation:")
    for entity, trail in sorted(report.row_count_reconciliation.items()):
        print(f"  {entity:>20}: {trail}")
    if report.status.value == "published":
        print(f"Published at: {report.published_at}")

    return 0 if report.status.value in ("certified", "published") else 2


if __name__ == "__main__":
    sys.exit(main())
