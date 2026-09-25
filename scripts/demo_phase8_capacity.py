#!/usr/bin/env python
"""End-to-end demonstration of Phase 8 (storage and compute footprint
management / capacity planning), run against REAL Phase 6/7 output --
not a hand-built fixture.

Like `scripts/demo_phase7_lifecycle.py`, this script deliberately imports
both `data_plane` (real certification pipeline run, real on-disk
footprint measurement) and `control_plane` (real Phase 7 lifecycle API,
real Phase 8 capacity-planning API) -- a standalone operator script, not
a plane-separation violation (see ADR-0003 and
`docs/adr/0013-capacity-planning-plane-split.md`). Neither service's own
installed package imports the other anywhere.

Usage::

    cd services/data-plane   # or run from repo root; both packages must be importable
    python ../../scripts/demo_phase8_capacity.py
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from healthcare_tdm_contracts import SubsettingStrategy, TERABYTE_BYTES

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app
from data_plane.capacity.footprint import measure_directory_footprint
from data_plane.capacity.partitioning import analyze_partitions
from data_plane.certification import signing as certification_signing
from data_plane.certification.pipeline import run_certification_pipeline
from data_plane.masking import secrets as masking_secrets

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "tmp" / "phase8-demo"


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def build_client(db_path: Path) -> TestClient:
    engine = create_sqlite_engine(str(db_path))
    factory = build_session_factory(engine)

    def _override():
        with session_scope(factory) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    return TestClient(app)


def main() -> int:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------
    # Step 1: a real certification pipeline run at `developer` scale --
    # big enough (hundreds of rows/file) that real Parquet compression
    # actually pays off; `tiny` scale genuinely does not (see
    # docs/CAPACITY_COST_TRADEOFFS.md for why that's an honest finding,
    # not a bug).
    # ------------------------------------------------------------------
    banner("STEP 1 -- Real certification pipeline run (developer scale)")
    masking_key = masking_secrets.generate_dev_key().encode("utf-8")
    signing_key = certification_signing.generate_dev_key().encode("utf-8")

    run1 = run_certification_pipeline(
        OUT_DIR / "run-v1",
        scale="developer",
        seed=20240101,
        subset_strategy=SubsettingStrategy.PERCENTAGE,
        subset_parameters={"percentage": "40"},
        masking_key=masking_key,
        signing_key=signing_key,
        dataset_name="phase8-demo-dataset",
        actor="phase8-demo-script",
        auto_publish=True,
    )
    print(f"Certification status: {run1.report.status.value.upper()}")

    # ------------------------------------------------------------------
    # Step 2: REAL footprint measurement (data-plane side) of the final,
    # certified output directory -- actual bytes, actual per-format
    # breakdown, actual Parquet-vs-CSV compression ratios.
    # ------------------------------------------------------------------
    banner("STEP 2 -- Real, on-disk footprint measurement (data_plane.capacity)")
    footprint = measure_directory_footprint(run1.final_dir)
    print(f"Total: {footprint.total_bytes:,} bytes across {footprint.total_file_count} files")
    print("By extension:", {ext: f"{size:,}b" for ext, size in footprint.bytes_by_extension.items()})
    if footprint.parquet_compression:
        overall_ratio = footprint.overall_parquet_compression_ratio
        print(
            f"Parquet: {footprint.total_parquet_compressed_bytes:,} bytes compressed vs. "
            f"{footprint.total_parquet_uncompressed_estimate_bytes:,} bytes as CSV "
            f"({overall_ratio:.2f}x smaller)" if overall_ratio else "no ratio computable"
        )
        for m in footprint.parquet_compression:
            print(f"    {Path(m.source_path).name}: {m.row_count} rows, {m.compression_ratio:.2f}x")

    partitions = analyze_partitions(run1.final_dir)
    if partitions.partition_key:
        print(f"Partitioning: key={partitions.partition_key!r}, {partitions.partition_count} partition(s)")

    row_counts = {
        entity: trail.split("final=")[-1].split()[0].strip(")")
        for entity, trail in run1.report.row_count_reconciliation.items()
    }
    row_counts = {k: int(v) for k, v in row_counts.items()}
    print(f"Row counts: {row_counts}")

    # ------------------------------------------------------------------
    # Step 3: register the measured footprint as dataset version 1, and
    # request it into all five example environments (Phase 7, unchanged).
    # ------------------------------------------------------------------
    banner("STEP 3 -- Register version 1 (real measured size_bytes/row_counts) and request 5 environments")
    client = build_client(OUT_DIR / "lifecycle.db")

    resp = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "phase8-demo-dataset",
            "certification_report": json.loads(run1.report.model_dump_json()),
            "storage_uri": str(run1.final_dir),
            "size_bytes": footprint.total_bytes,
            "row_counts": row_counts,
            "created_by": "phase8-demo-script",
        },
    )
    assert resp.status_code == 201, resp.text
    version_1 = resp.json()

    for env, consumer in [
        ("dev", "claims-dev-team"), ("qa", "claims-qa-team"), ("sit", "integration-test-team"),
        ("uat", "release-readiness-team"), ("performance", "perf-engineering-team"),
    ]:
        resp = client.post(
            "/api/v1/lifecycle/environment-requests",
            json={"environment": env, "dataset_name": "phase8-demo-dataset", "requested_by": "phase8-demo-script", "consumer": consumer},
        )
        assert resp.status_code == 201, resp.text

    # ------------------------------------------------------------------
    # Step 4: the real, DB-backed capacity plan -- naive vs. shared.
    # ------------------------------------------------------------------
    banner("STEP 4 -- Real capacity plan: naive-if-independent-copies vs. Phase 7's real shared-snapshot cost")
    plan = client.get("/api/v1/capacity/plan", params={"dataset_name": "phase8-demo-dataset"}).json()
    print(f"Environments requesting this dataset: {plan['environment_count']}")
    print(f"Distinct physical dataset versions actually stored: {plan['distinct_dataset_version_count']}")
    print(f"Naive total (if each environment had its own copy): {plan['naive_total_storage_bytes']:,} bytes")
    print(f"Actual shared total (Phase 7's real architecture):   {plan['shared_total_storage_bytes']:,} bytes")
    print(f"Savings: {plan['storage_savings_bytes']:,} bytes ({plan['storage_savings_pct'] * 100:.1f}%)")

    for demand in plan["environment_demands"]:
        refreshes = demand["estimated_refreshes_per_year"]
        refreshes_str = f"{refreshes:.1f}/yr" if refreshes is not None else "no fixed cadence"
        print(f"  {demand['environment']:>12}: cadence={demand['refresh_cadence_type']:<15} {refreshes_str}")

    # ------------------------------------------------------------------
    # Step 5: vacuum candidates -- register v2, leave it unreferenced,
    # revoke it, confirm it (and only it) shows up as reclaimable.
    # ------------------------------------------------------------------
    banner("STEP 5 -- Vacuum candidates: an unreferenced, revoked version is identified as reclaimable")
    run2 = run_certification_pipeline(
        OUT_DIR / "run-v2", scale="developer", seed=20240102,
        subset_strategy=SubsettingStrategy.PERCENTAGE, subset_parameters={"percentage": "10"},
        masking_key=masking_key, signing_key=signing_key,
        dataset_name="phase8-demo-dataset", actor="phase8-demo-script", auto_publish=True,
    )
    footprint_2 = measure_directory_footprint(run2.final_dir)
    resp = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "phase8-demo-dataset",
            "certification_report": json.loads(run2.report.model_dump_json()),
            "storage_uri": str(run2.final_dir),
            "size_bytes": footprint_2.total_bytes,
            "row_counts": {},
            "created_by": "phase8-demo-script",
        },
    )
    version_2 = resp.json()
    print(f"Registered version 2 (size={footprint_2.total_bytes:,} bytes) -- no environment ever requests it.")
    resp = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version_2['version_id']}/revoke",
        json={"reason": "demonstration: never adopted, safe to reclaim", "revoked_by": "ops@example.org"},
    )
    assert resp.status_code == 200, resp.text

    candidates = client.get("/api/v1/capacity/vacuum-candidates", params={"dataset_name": "phase8-demo-dataset"}).json()
    print(f"Vacuum candidates: {len(candidates)}")
    for c in candidates:
        print(f"  version_number={c['version_number']} status={c['status']} reclaimable_bytes={c['reclaimable_bytes']:,} reason={c['reason']!r}")
    print(f"Version 1 (still referenced by 5 environments) correctly does NOT appear above.")

    # ------------------------------------------------------------------
    # Step 6: the illustrative "Production: 100 TB" scenario from
    # ROADMAP.md, computed via the real API with zero setup.
    # ------------------------------------------------------------------
    banner("STEP 6 -- Illustrative scenario: Production 100 TB, QA 10%, SIT 5%, UAT 15%, DEV 10%, PERFORMANCE 100%")
    illustrative = client.get("/api/v1/capacity/illustrative-plan").json()
    tb = TERABYTE_BYTES
    print(f"Production baseline: {illustrative['scenario']['production_baseline_bytes'] / tb:.0f} TB")
    for env, bytes_ in illustrative["per_environment_naive_bytes"].items():
        print(f"  {env:>12}: naive independent copy = {bytes_ / tb:.1f} TB")
    print(f"Naive total (5 independent copies):  {illustrative['naive_total_bytes'] / tb:.1f} TB")
    for tier, bytes_ in illustrative["per_tier_shared_bytes"].items():
        print(f"  tier={tier:<12}: shared snapshot = {bytes_ / tb:.1f} TB")
    print(f"Shared total (Phase 7-style sharing by tier): {illustrative['shared_total_bytes'] / tb:.1f} TB")
    print(f"Savings: {illustrative['savings_bytes'] / tb:.1f} TB ({illustrative['savings_pct'] * 100:.1f}%)")

    banner("DONE -- Phase 8 capacity planning demo completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
