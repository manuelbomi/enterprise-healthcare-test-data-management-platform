"""Command-line entry point for masking a generated synthetic estate.

Usage::

    # 1. Generate an estate (Phase 1 CLI) if you don't already have one:
    python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

    # 2. Run discovery against it (Phase 2 CLI) to produce a catalog:
    python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \\
        --out data/tmp/synthetic-estate/catalog.json

    # 3. Resolve a local dev HMAC key (never commit it -- see SECURITY.md):
    python -m data_plane.masking.cli --generate-dev-key
    export TDM_MASKING_HMAC_KEY=<the printed value>

    # 4. Mask the estate using the catalog's classification:
    python -m data_plane.masking.cli --estate-dir data/tmp/synthetic-estate \\
        --catalog data/tmp/synthetic-estate/catalog.json \\
        --out-dir data/tmp/synthetic-estate-masked

``--out-dir`` defaults to ``<estate-dir>-masked``, which -- like the
estate and catalog it reads -- lives under the repository's
``**/data/tmp/`` `.gitignore` rule when placed under ``data/tmp/``:
masked output is exactly as disposable/reproducible as the estate and
catalog that produced it (same key + same estate + same catalog always
reproduces the same masked output -- see ADR-0006).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from healthcare_tdm_contracts import MaskingRunSummary

from data_plane.discovery.catalog_builder import load_catalog
from data_plane.masking import secrets as masking_secrets
from data_plane.masking.dataset_masker import mask_estate
from data_plane.masking.engine import MaskingEngine
from data_plane.masking.policy import DEFAULT_POLICY
from data_plane.masking.validation import validate_masking_run


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Mask the SYNTHETIC multi-system healthcare estate using its data catalog."
    )
    parser.add_argument(
        "--generate-dev-key",
        action="store_true",
        help=(
            "Print a freshly generated, random HMAC key for LOCAL DEVELOPMENT/TESTING "
            "ONLY, then exit. Never written to disk by this command -- export it "
            "yourself (TDM_MASKING_HMAC_KEY=...) or paste it into a gitignored .env "
            "file. Never use this for anything beyond local experimentation, and "
            "never commit it anywhere."
        ),
    )
    parser.add_argument("--estate-dir", default=None, help="Output directory of a reference_data.cli run.")
    parser.add_argument(
        "--catalog", default=None, help="Path to the catalog.json a discovery.cli run wrote."
    )
    parser.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for the masked estate (default: <estate-dir>-masked).",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)

    if args.generate_dev_key:
        key = masking_secrets.generate_dev_key()
        print(
            "Generated a LOCAL DEV/TEST-ONLY HMAC key (never written to disk, never "
            "the same twice, never valid for anything beyond your local shell):\n"
        )
        print(f"  {masking_secrets.ENV_VAR}={key}\n")
        print(
            "Export it for this shell session, or paste it into a gitignored "
            "services/data-plane/.env file (see .env.example). Do not commit it "
            "anywhere, do not reuse it across environments, and do not treat it as "
            "a real secret."
        )
        return 0

    if not args.estate_dir or not args.catalog:
        print("--estate-dir and --catalog are required unless --generate-dev-key is set.", file=sys.stderr)
        return 1

    estate_dir = Path(args.estate_dir)
    catalog_path = Path(args.catalog)
    if not estate_dir.exists():
        print(f"Estate directory '{estate_dir}' does not exist.", file=sys.stderr)
        return 1
    if not catalog_path.exists():
        print(
            f"Catalog '{catalog_path}' does not exist. Generate one first with "
            f"'python -m data_plane.discovery.cli --estate-dir {estate_dir}'.",
            file=sys.stderr,
        )
        return 1

    out_dir = Path(args.out_dir) if args.out_dir else estate_dir.parent / f"{estate_dir.name}-masked"

    try:
        key = masking_secrets.resolve_hmac_key()
    except (masking_secrets.MissingMaskingKeyError, masking_secrets.WeakMaskingKeyError) as exc:
        print(str(exc), file=sys.stderr)
        return 1

    engine = MaskingEngine(key=key)
    catalog_entries = load_catalog(catalog_path)
    policy_used = DEFAULT_POLICY
    report = mask_estate(estate_dir, catalog_entries, out_dir, engine, policy=policy_used)

    validation = validate_masking_run(linkage_samples=report.linkage_samples)

    print(f"Masked estate written: {out_dir}")
    print(f"Rows processed: {report.rows_processed}")
    print(f"Column-values masked: {report.columns_masked}")
    print("By technique:")
    for technique, count in sorted(report.technique_counts.items()):
        print(f"  {technique:>28}: {count}")
    print(f"Files written: {len(report.files_written)}")
    if report.warnings:
        print(f"Warnings (malformed values encountered, handled safely): {len(report.warnings)}")
    print(f"Validation: {'PASSED' if validation.passed else 'FAILED'} ({len(validation.checks_run)} checks)")
    if not validation.passed:
        for failure in validation.failures:
            print(f"  FAILED: {failure}", file=sys.stderr)

    # Phase 18B (`problems_final_review.md` P3-7): constructs the shared
    # `healthcare_tdm_contracts.MaskingRunSummary` contract rather than a
    # raw dict -- the same shape
    # `data_plane.certification.pipeline._write_masking_summary` builds,
    # and the one `control_plane.artifacts.masking` now imports directly
    # to parse this same file back, instead of each of the three
    # maintaining its own copy of this field list.
    summary_model = MaskingRunSummary(
        rows_processed=report.rows_processed,
        columns_masked=report.columns_masked,
        technique_counts=report.technique_counts,
        files_written=[str(p) for p in report.files_written],
        warning_count=len(report.warnings),
        masking_engine_version=report.masking_engine_version,
        policy_name=(policy_used.name if policy_used else None),
        policy_version=(policy_used.version if policy_used else None),
        validation_passed=validation.passed,
        validation_checks=validation.checks_run,
        validation_failures=validation.failures,
    )
    summary_path = out_dir / "masking_run_summary.json"
    summary_path.write_text(summary_model.model_dump_json(indent=2), encoding="utf-8")
    print(f"Run summary: {summary_path}")

    return 0 if validation.passed else 2


if __name__ == "__main__":
    sys.exit(main())
