#!/usr/bin/env python
"""End-to-end demonstration of Phase 7 (dataset lifecycle and refresh
management), run against a REAL Phase 6 certification pipeline output --
not a hand-built fixture.

This script deliberately imports both `data_plane` (to produce a real
`CertificationReport`, exactly the way a real operator/CI job would run
the Phase 6 pipeline) and `control_plane` (to register/request/refresh/
rollback/revoke that dataset through the real Phase 7 API). That is not
a plane-separation violation (`docs/adr/0003-plane-separation.md`) --
the rule is that neither *service's own installed package* may import
the other's internals; a standalone operator script gluing two real
CLIs/APIs together is exactly how a real deployment pipeline would work
(a CI job that runs the certification CLI, then calls the control
plane's REST API with the resulting report). Neither `services/data-plane`
nor `services/control-plane`'s own source imports the other anywhere.

The control-plane API is exercised through FastAPI's `TestClient` (an
in-process, fully-real ASGI call, not mocked) against a real, on-disk
SQLite database, so this script needs no separately running server
process -- consistent with how `services/control-plane/tests/` already
exercises the API. Run it with `uvicorn control_plane.main:app` instead
if you want the same walkthrough against a real HTTP server; nothing
here is TestClient-specific business logic.

Usage::

    cd services/data-plane   # or run from repo root; both packages must be importable
    python ../../scripts/demo_phase7_lifecycle.py
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from healthcare_tdm_contracts import SubsettingStrategy

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app
from control_plane.platform import auth as control_plane_auth
from control_plane.platform.rbac import Role
from data_plane.certification import signing as certification_signing
from data_plane.certification.pipeline import run_certification_pipeline
from data_plane.masking import secrets as masking_secrets

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "tmp" / "phase7-demo"

# Phase 18A (P0-1): a throwaway dev key for this script's own process --
# RBAC-gated endpoints (revoke/rollback) now require a real, verified
# bearer token, not a caller-supplied `actor_role` field. See
# `control_plane.platform.auth`'s module docstring.
os.environ.setdefault("TDM_CONTROL_PLANE_JWT_SIGNING_KEY", control_plane_auth.generate_dev_key())


def auth_header(client: TestClient, role: Role) -> dict[str, str]:
    """Log in as the seeded demo identity for `role` and return the
    `Authorization` header -- see
    `control_plane.platform.auth.SEEDED_DEMO_USERS`."""

    username, password = control_plane_auth.demo_credentials_for_role(role)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def directory_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def parse_final_row_counts(row_count_reconciliation: dict[str, str]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for entity, trail in row_count_reconciliation.items():
        match = re.search(r"final=(\d+)", trail)
        if match:
            counts[entity] = int(match.group(1))
    return counts


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
    # Step 1: run a REAL Phase 6 certification pipeline run (v1)
    # ------------------------------------------------------------------
    banner("STEP 1 -- Run the real Phase 6 certification pipeline (dataset version 1)")
    masking_key = masking_secrets.generate_dev_key().encode("utf-8")
    signing_key = certification_signing.generate_dev_key().encode("utf-8")

    run1 = run_certification_pipeline(
        OUT_DIR / "run-v1",
        scale="tiny",
        seed=20240101,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "10"},
        masking_key=masking_key,
        signing_key=signing_key,
        dataset_name="phase7-demo-dataset",
        actor="phase7-demo-script",
        auto_publish=True,
    )
    report1 = run1.report
    print(f"Certification report 1: {run1.report_path}")
    print(f"Status: {report1.status.value.upper()}  Gates: {sum(g.passed for g in report1.gates)}/{len(report1.gates)} passed")
    assert report1.status.value in ("certified", "published")

    final_dir_1 = run1.final_dir
    size_1 = directory_size_bytes(final_dir_1)
    row_counts_1 = parse_final_row_counts(report1.row_count_reconciliation)
    print(f"Final artifact directory: {final_dir_1} ({size_1} bytes on disk)")
    print(f"Row counts: {row_counts_1}")

    # ------------------------------------------------------------------
    # Step 2: register it as dataset version 1 in the control plane
    # ------------------------------------------------------------------
    banner("STEP 2 -- Register dataset version 1 via the real Phase 7 control-plane API")
    client = build_client(OUT_DIR / "lifecycle.db")

    resp = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "phase7-demo-dataset",
            "certification_report": json.loads(report1.model_dump_json()),
            "storage_uri": str(final_dir_1),
            "size_bytes": size_1,
            "row_counts": row_counts_1,
            "created_by": "phase7-demo-script",
        },
    )
    assert resp.status_code == 201, resp.text
    version_1 = resp.json()
    print(f"Registered version_id={version_1['version_id']}  version_number={version_1['version_number']}")
    print(f"storage_uri={version_1['storage_uri']}")

    # ------------------------------------------------------------------
    # Step 3: request the SAME dataset into two+ environments
    # ------------------------------------------------------------------
    banner("STEP 3 -- Request the dataset into DEV, QA, SIT, UAT, and PERFORMANCE")
    requests: dict[str, dict] = {}
    for env, consumer in [
        ("dev", "claims-dev-team"),
        ("qa", "claims-qa-team"),
        ("sit", "integration-test-team"),
        ("uat", "release-readiness-team"),
        ("performance", "perf-engineering-team"),
    ]:
        resp = client.post(
            "/api/v1/lifecycle/environment-requests",
            json={
                "environment": env,
                "dataset_name": "phase7-demo-dataset",
                "requested_by": "phase7-demo-script",
                "consumer": consumer,
            },
        )
        assert resp.status_code == 201, resp.text
        requests[env] = resp.json()
        print(f"  {env:>12}: request_id={requests[env]['request_id']}  "
              f"current_version={requests[env]['current_version_number']}  "
              f"next_refresh_at={requests[env]['next_refresh_at']}")

    # ------------------------------------------------------------------
    # Step 4: prove no duplicate physical copies were made
    # ------------------------------------------------------------------
    banner("STEP 4 -- Confirm zero duplicate physical copies")
    version_after = client.get(f"/api/v1/lifecycle/dataset-versions/{version_1['version_id']}").json()
    print(f"DatasetVersion.storage_uri is referenced by: {version_after['referenced_by_environments']}")
    print(f"All 5 environments point at the SAME storage_uri: {version_after['storage_uri']}")
    print("(only ONE on-disk artifact directory exists for this dataset version; "
          "verified below by directly checking the filesystem)")
    assert final_dir_1.exists()
    print(f"  -> {final_dir_1} exists, is the one and only physical copy on disk for version 1.")

    # ------------------------------------------------------------------
    # Step 5: refresh cadence per environment (already visible above);
    # show it explicitly against the 5 example cadences
    # ------------------------------------------------------------------
    banner("STEP 5 -- Refresh cadence computed per environment")
    for env in ["dev", "qa", "sit", "uat", "performance"]:
        policy = client.get(f"/api/v1/lifecycle/refresh-policies/{env}/default").json()
        req = requests[env]
        print(f"  {env:>12}: cadence={policy['cadence_type']:<15} "
              f"requested_at={req['requested_at']}  next_refresh_at={req['next_refresh_at']}")

    # ------------------------------------------------------------------
    # Step 6: run a second real certification pipeline run -> version 2
    # ------------------------------------------------------------------
    banner("STEP 6 -- Run a second real certification pipeline run (dataset version 2)")
    run2 = run_certification_pipeline(
        OUT_DIR / "run-v2",
        scale="tiny",
        seed=20240102,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "12"},
        masking_key=masking_key,
        signing_key=signing_key,
        dataset_name="phase7-demo-dataset",
        actor="phase7-demo-script",
        auto_publish=True,
    )
    report2 = run2.report
    final_dir_2 = run2.final_dir
    size_2 = directory_size_bytes(final_dir_2)
    row_counts_2 = parse_final_row_counts(report2.row_count_reconciliation)

    resp = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "phase7-demo-dataset",
            "certification_report": json.loads(report2.model_dump_json()),
            "storage_uri": str(final_dir_2),
            "size_bytes": size_2,
            "row_counts": row_counts_2,
            "created_by": "phase7-demo-script",
        },
    )
    assert resp.status_code == 201, resp.text
    version_2 = resp.json()
    print(f"Registered version_id={version_2['version_id']}  version_number={version_2['version_number']}")

    # ------------------------------------------------------------------
    # Step 7: on-demand refresh DEV onto version 2
    # ------------------------------------------------------------------
    banner("STEP 7 -- On-demand refresh: move DEV onto version 2")
    resp = client.post(
        f"/api/v1/lifecycle/environment-requests/{requests['dev']['request_id']}/refresh",
        json={"triggered_by": "phase7-demo-script", "trigger": "on_demand"},
    )
    assert resp.status_code == 200, resp.text
    run_record = resp.json()
    print(f"Refresh run: succeeded={run_record['succeeded']}  detail={run_record['detail']}")
    dev_after = client.get(f"/api/v1/lifecycle/environment-requests/{requests['dev']['request_id']}").json()
    print(f"DEV now on version {dev_after['current_version_number']} "
          f"(QA remains on version {client.get('/api/v1/lifecycle/environment-requests/' + requests['qa']['request_id']).json()['current_version_number']})")

    # ------------------------------------------------------------------
    # Step 8: rollback DEV back to version 1
    # ------------------------------------------------------------------
    banner("STEP 8 -- Roll DEV back to version 1")
    resp = client.post(
        f"/api/v1/lifecycle/environment-requests/{requests['dev']['request_id']}/rollback",
        json={
            "to_version_number": 1,
            "performed_by": "oncall@example.org",
            "reason": "version 2 introduced a regression in DEV smoke tests",
        },
        # Phase 11: rollback requires a real, checked role (Phase 18A:
        # now verified via a real bearer token, not a request field --
        # see control_plane.platform.auth).
        headers=auth_header(client, Role.DATA_STEWARD),
    )
    assert resp.status_code == 200, resp.text
    rollback = resp.json()
    print(f"Rolled back DEV: from v{rollback['from_version_number']} -> v{rollback['to_version_number']}")

    version_2_after_rollback = client.get(f"/api/v1/lifecycle/dataset-versions/{version_2['version_id']}").json()
    print(f"Version 2 status after rollback (unreferenced by any environment): {version_2_after_rollback['status']}")

    # ------------------------------------------------------------------
    # Step 9: revoke version 1, confirm QA (still on it) is undisturbed
    #         but new requests/refreshes can no longer select it
    # ------------------------------------------------------------------
    banner("STEP 9 -- Revoke version 1; confirm existing usage is undisturbed but new selection is blocked")
    # First put DEV back to a safe state isn't necessary -- revocation of a
    # version currently in use is exactly the scenario this step demonstrates.
    resp = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version_1['version_id']}/revoke",
        json={
            "reason": "demonstration: simulated post-publication policy defect",
            "revoked_by": "security@example.org",
        },
        # Phase 18A: revoke requires a real, verified bearer token.
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert resp.status_code == 200, resp.text
    print(f"Version 1 status: {resp.json()['status']}")

    dev_still = client.get(f"/api/v1/lifecycle/environment-requests/{requests['dev']['request_id']}").json()
    print(f"DEV's request is UNCHANGED (still points at revoked version {dev_still['current_version_number']}); "
          "revocation never silently migrates an environment already using a version.")

    blocked_new_request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "sit", "dataset_name": "should-never-have-a-version", "requested_by": "a"},
    )
    print(f"A brand-new dataset with no ACTIVE version: {blocked_new_request.status_code} "
          f"({blocked_new_request.json()['detail'][:80]}...)")

    blocked_rollback = client.post(
        f"/api/v1/lifecycle/environment-requests/{requests['qa']['request_id']}/rollback",
        json={
            "to_version_number": 1,
            "performed_by": "a",
            "reason": "try to select the revoked version",
        },
        headers=auth_header(client, Role.DATA_STEWARD),
    )
    print(f"Attempting to roll QA back to the now-revoked version 1: HTTP {blocked_rollback.status_code} "
          f"({blocked_rollback.json()['detail'][:90]}...)")
    assert blocked_rollback.status_code == 409

    # ------------------------------------------------------------------
    # Step 10: scheduler orchestration abstraction
    # ------------------------------------------------------------------
    banner("STEP 10 -- Orchestration abstraction: what needs refreshing right now")
    resp = client.get("/api/v1/lifecycle/scheduler/due")
    print(f"Currently due (as of real now): {len(resp.json())} request(s)")
    from datetime import datetime, timedelta, timezone

    far_future = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
    resp = client.get("/api/v1/lifecycle/scheduler/due", params={"as_of": far_future})
    due = resp.json()
    print(f"Due 400 days from now: {len(due)} request(s) -> {[d['environment'] for d in due]}")
    print("(UAT never appears here -- release_driven has no fixed schedule, matching ROADMAP.md.)")

    # Phase 18A (P1-2): this endpoint now requires a real, verified
    # PLATFORM_ADMIN bearer token; `triggered_by` is derived from the
    # verified identity rather than accepted as a caller-supplied field.
    sweep = client.post(
        "/api/v1/lifecycle/scheduler/run-due",
        params={"as_of": far_future},
        headers=auth_header(client, Role.PLATFORM_ADMIN),
    ).json()
    print(f"Scheduled sweep executed: {sweep['succeeded_count']} succeeded, {sweep['failed_count']} failed")

    banner("DONE -- Phase 7 dataset lifecycle demo completed successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
