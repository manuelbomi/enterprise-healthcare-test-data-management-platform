#!/usr/bin/env python
"""End-to-end demonstration of Phase 10 (centralized enterprise masking
governance), run against REAL Phase 3/6/7/8 machinery -- not hand-built
fixtures standing in for them.

Like `demo_phase7_lifecycle.py`, this script deliberately imports both
`data_plane` (to run two real Phase 6 certification pipeline runs, using
the real Phase 3 `DEFAULT_POLICY`) and `control_plane` (to drive the
real Phase 10 governance API, which itself calls directly into the real
Phase 7 lifecycle API and is read by the real Phase 8 `CapacityPlanner`).
This is not a plane-separation violation (`docs/adr/0003-plane-separation.md`)
for the same reason `demo_phase7_lifecycle.py` documents: a standalone
operator script gluing two real services together is exactly how a real
deployment pipeline works. Neither `services/data-plane` nor
`services/control-plane`'s own source imports the other anywhere.

What this script proves, narrated as it runs:

1. A real Phase 3 `MaskingPolicy` (`data_plane.masking.policy.DEFAULT_POLICY`)
   is drafted as a governed `MaskingPolicyVersion`, submitted, and
   approved -- a real, enforced approval-workflow state machine, not a
   config flag.
2. Two named business consumers, LEFT_ARM and RIGHT_ARM, are registered.
3. Two REAL Phase 6 certification pipeline runs execute -- different
   subset sizes, same governed policy object (passed explicitly, not
   just matching by name/version coincidentally) -- producing two real,
   signed `CertificationReport`s, registered as two Phase 7
   `DatasetVersion`s.
4. LEFT_ARM and RIGHT_ARM each submit a `ConsumerDatasetRequest` for
   their own dataset/environment/subset-size/cadence/performance
   requirements, both referencing the SAME approved
   `MaskingPolicyVersion` -- proven by comparing `policy_version_id`.
5. RIGHT_ARM requests ADDITIONAL QA capacity, with its own refresh
   cadence. Fulfilling it calls directly into the real Phase 7
   `LifecycleRepository`/API -- a new `EnvironmentDatasetRequest` row,
   not a parallel system -- and the real Phase 8 `CapacityPlanner`
   output changes to reflect it, shown before/after.
6. An attempt to submit a consumer request against an unapproved policy
   version is rejected (HTTP 409) -- the adversarial-bypass proof that
   there is no path around central governance.

Usage::

    cd services/data-plane   # or run from repo root; both packages must be importable
    python ../../scripts/demo_phase10_governance.py
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
from data_plane.masking.engine import MASKING_ENGINE_VERSION
from data_plane.masking.policy import DEFAULT_POLICY

REPO_ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = REPO_ROOT / "data" / "tmp" / "phase10-demo"

# Phase 18A (P0-1): see demo_phase7_lifecycle.py's identical note.
os.environ.setdefault("TDM_CONTROL_PLANE_JWT_SIGNING_KEY", control_plane_auth.generate_dev_key())


def auth_header(client: TestClient, role: Role) -> dict[str, str]:
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

    client = build_client(OUT_DIR / "governance.db")

    # ------------------------------------------------------------------
    # Step 1: draft, submit, and approve the ONE governed masking policy
    # ------------------------------------------------------------------
    banner("STEP 1 -- Draft, submit, and approve the centrally governed masking policy")
    print(f"Wrapping the real Phase 3 DEFAULT_POLICY: name={DEFAULT_POLICY.name!r} "
          f"version={DEFAULT_POLICY.version} rule_count={len(DEFAULT_POLICY.rules)} "
          f"masking_engine_version={MASKING_ENGINE_VERSION!r}")

    draft_resp = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(DEFAULT_POLICY.model_dump_json()),
            "masking_engine_version": MASKING_ENGINE_VERSION,
            "created_by": "governance-admin@example.org",
            "notes": "Enterprise-standard masking policy for all business consumers.",
        },
    )
    assert draft_resp.status_code == 201, draft_resp.text
    policy_version = draft_resp.json()
    print(f"Drafted MaskingPolicyVersion {policy_version['policy_version_id']} "
          f"(status={policy_version['approval_status']})")

    submit_resp = client.post(
        f"/api/v1/governance/policy-versions/{policy_version['policy_version_id']}/submit",
        json={"performed_by": "governance-admin@example.org"},
    )
    assert submit_resp.status_code == 200, submit_resp.text
    print(f"Submitted for approval (status={submit_resp.json()['approval_status']})")

    approve_resp = client.post(
        f"/api/v1/governance/policy-versions/{policy_version['policy_version_id']}/approve",
        json={
            "performed_by": "compliance-steward@example.org",
            "comments": "Reviewed against DATA_GOVERNANCE.md B.2; approved for enterprise-wide use.",
        },
        # Phase 11: approval requires a real, checked role (Phase 18A:
        # now a verified bearer token, not a request field).
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert approve_resp.status_code == 200, approve_resp.text
    approved_policy = approve_resp.json()
    print(f"APPROVED by compliance-steward@example.org -> status={approved_policy['approval_status']}")

    approvals = client.get(
        f"/api/v1/governance/policy-versions/{approved_policy['policy_version_id']}/approvals"
    ).json()
    print("Approval audit trail:")
    for a in approvals:
        print(f"  {a['performed_at']}  {a['performed_by']:<32} -> {a['status']}")

    # ------------------------------------------------------------------
    # Step 2: register the two business consumers
    # ------------------------------------------------------------------
    banner("STEP 2 -- Register the two organizational arms")
    left = client.post(
        "/api/v1/governance/business-consumers",
        json={
            "code": "LEFT_ARM",
            "display_name": "Left Arm Business Unit",
            "description": "Claims operations arm.",
            "contact": "left-arm-platform@example.org",
        },
    ).json()
    right = client.post(
        "/api/v1/governance/business-consumers",
        json={
            "code": "RIGHT_ARM",
            "display_name": "Right Arm Business Unit",
            "description": "Clinical analytics arm.",
            "contact": "right-arm-platform@example.org",
        },
    ).json()
    print(f"LEFT_ARM  business_consumer_id={left['business_consumer_id']}")
    print(f"RIGHT_ARM business_consumer_id={right['business_consumer_id']}")

    # ------------------------------------------------------------------
    # Step 3: two REAL certification pipeline runs, same governed policy,
    #         different subset sizes -- one per arm
    # ------------------------------------------------------------------
    banner("STEP 3 -- Run two real Phase 6 certification pipelines under the SAME governed policy")
    masking_key = masking_secrets.generate_dev_key().encode("utf-8")
    signing_key = certification_signing.generate_dev_key().encode("utf-8")
    # The exact policy object the governance layer just approved -- not
    # merely a policy that happens to share a name/version.
    governed_policy = DEFAULT_POLICY

    left_run = run_certification_pipeline(
        OUT_DIR / "left-arm-run",
        scale="tiny",
        seed=20241001,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "8"},
        masking_key=masking_key,
        masking_policy=governed_policy,
        dataset_name="left-arm-member-claims-subset",
        actor="phase10-demo-script",
        signing_key=signing_key,
        auto_publish=True,
    )
    right_run = run_certification_pipeline(
        OUT_DIR / "right-arm-run",
        scale="tiny",
        seed=20241002,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "20"},
        masking_key=masking_key,
        masking_policy=governed_policy,
        dataset_name="right-arm-member-claims-subset",
        actor="phase10-demo-script",
        signing_key=signing_key,
        auto_publish=True,
    )
    for label, run in (("LEFT_ARM", left_run), ("RIGHT_ARM", right_run)):
        report = run.report
        print(f"  {label}: report={report.report_id}  status={report.status.value.upper()}  "
              f"policy={report.masking_policy_name}@{report.masking_policy_version}  "
              f"engine={report.masking_engine_version}  "
              f"gates_passed={sum(g.passed for g in report.gates)}/{len(report.gates)}")
        assert report.status.value in ("certified", "published")
        assert report.masking_policy_name == approved_policy["policy_name"]
        assert report.masking_policy_version == approved_policy["policy_version"]

    # ------------------------------------------------------------------
    # Step 4: register both as real Phase 7 dataset versions
    # ------------------------------------------------------------------
    banner("STEP 4 -- Register both certified datasets as real Phase 7 DatasetVersions")
    dataset_versions: dict[str, dict] = {}
    for label, run, dataset_name in (
        ("LEFT_ARM", left_run, "left-arm-member-claims-subset"),
        ("RIGHT_ARM", right_run, "right-arm-member-claims-subset"),
    ):
        report = run.report
        size = directory_size_bytes(run.final_dir)
        row_counts = parse_final_row_counts(report.row_count_reconciliation)
        resp = client.post(
            "/api/v1/lifecycle/dataset-versions",
            json={
                "dataset_name": dataset_name,
                "certification_report": json.loads(report.model_dump_json()),
                "storage_uri": str(run.final_dir),
                "size_bytes": size,
                "row_counts": row_counts,
                "created_by": "phase10-demo-script",
            },
        )
        assert resp.status_code == 201, resp.text
        dataset_versions[label] = resp.json()
        print(f"  {label}: version_id={dataset_versions[label]['version_id']} "
              f"({size} bytes, rows={row_counts})")

    # ------------------------------------------------------------------
    # Step 5: both arms submit ConsumerDatasetRequests -- same policy
    # ------------------------------------------------------------------
    banner("STEP 5 -- Both arms request datasets, referencing the SAME approved policy version")
    left_request = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": left["business_consumer_id"],
            "dataset_name": "left-arm-member-claims-subset",
            "environment": "dev",
            "policy_version_id": approved_policy["policy_version_id"],
            "subset_size_hint": "1% of members, fixed population of 8 for local dev",
            "refresh_cadence_type": "weekly",
            "performance_requirements": "standard dev-loop latency",
            "requested_by": "left-arm-lead@example.org",
        },
    ).json()
    right_request = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": right["business_consumer_id"],
            "dataset_name": "right-arm-member-claims-subset",
            "environment": "dev",
            "policy_version_id": approved_policy["policy_version_id"],
            "subset_size_hint": "larger fixed population of 20 for analytics dev",
            "refresh_cadence_type": "weekly",
            "performance_requirements": "standard dev-loop latency",
            "requested_by": "right-arm-lead@example.org",
        },
    ).json()
    print(f"  LEFT_ARM  -> policy_version_id={left_request['policy_version_id']}")
    print(f"  RIGHT_ARM -> policy_version_id={right_request['policy_version_id']}")
    assert left_request["policy_version_id"] == right_request["policy_version_id"] == approved_policy["policy_version_id"]
    print("  CONFIRMED: both arms' requests resolve to the identical governed policy_version_id.")

    for label, req in (("LEFT_ARM", left_request), ("RIGHT_ARM", right_request)):
        resp = client.post(
            f"/api/v1/governance/consumer-requests/{req['consumer_request_id']}/fulfill",
            json={"triggered_by": "governance-service"},
        )
        assert resp.status_code == 200, resp.text
        print(f"  {label} DEV request fulfilled -> environment_request_id={resp.json()['environment_request_id']}")

    # ------------------------------------------------------------------
    # Step 6: capacity plan BEFORE RIGHT_ARM's additional QA request
    # ------------------------------------------------------------------
    banner("STEP 6 -- Real Phase 8 capacity plan BEFORE RIGHT_ARM's additional QA capacity request")
    plan_before = client.get("/api/v1/capacity/plan").json()
    print(f"  environment_count={plan_before['environment_count']}  "
          f"distinct_dataset_version_count={plan_before['distinct_dataset_version_count']}  "
          f"shared_total_storage_bytes={plan_before['shared_total_storage_bytes']}")
    for d in plan_before["environment_demands"]:
        print(f"    {d['environment']:<12} {d['dataset_name']:<32} cadence={d['refresh_cadence_type']}")

    # ------------------------------------------------------------------
    # Step 7: RIGHT_ARM requests ADDITIONAL QA capacity -- scheduled into
    #         the EXISTING refresh calendar/capacity plan
    # ------------------------------------------------------------------
    banner("STEP 7 -- RIGHT_ARM requests ADDITIONAL QA capacity (different cadence, higher volume)")
    right_qa_request = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": right["business_consumer_id"],
            "dataset_name": "right-arm-member-claims-subset",
            "environment": "qa",
            "policy_version_id": approved_policy["policy_version_id"],
            "subset_size_hint": "high-volume regression set, fixed population of 20 refreshed twice as often",
            "refresh_cadence_type": "biweekly",
            "performance_requirements": "parallel regression suite, sub-200ms p95 query latency",
            "requested_by": "right-arm-lead@example.org",
            "notes": "Additional QA capacity for the Q3 regression push.",
        },
    )
    assert right_qa_request.status_code == 201, right_qa_request.text
    right_qa_request = right_qa_request.json()
    assert right_qa_request["policy_version_id"] == approved_policy["policy_version_id"]
    print(f"  Submitted: consumer_request_id={right_qa_request['consumer_request_id']} "
          f"policy_version_id={right_qa_request['policy_version_id']} (SAME governed policy)")

    right_qa_fulfilled = client.post(
        f"/api/v1/governance/consumer-requests/{right_qa_request['consumer_request_id']}/fulfill",
        json={"triggered_by": "governance-service"},
    )
    assert right_qa_fulfilled.status_code == 200, right_qa_fulfilled.text
    right_qa_fulfilled = right_qa_fulfilled.json()
    qa_env_request_id = right_qa_fulfilled["environment_request_id"]
    print(f"  Fulfilled into a REAL Phase 7 EnvironmentDatasetRequest: {qa_env_request_id}")

    qa_env_request = client.get(f"/api/v1/lifecycle/environment-requests/{qa_env_request_id}").json()
    print(f"  Phase 7 confirms: environment={qa_env_request['environment']} "
          f"dataset_name={qa_env_request['dataset_name']} consumer={qa_env_request['consumer']!r} "
          f"next_refresh_at={qa_env_request['next_refresh_at']}")

    qa_policy = client.get("/api/v1/lifecycle/refresh-policies", params={"environment": "qa"}).json()
    right_qa_policy = next(p for p in qa_policy if p["dataset_name"] == "right-arm-member-claims-subset")
    print(f"  Phase 7 refresh policy for (QA, right-arm-member-claims-subset): "
          f"cadence_type={right_qa_policy['cadence_type']} (RIGHT_ARM's requested cadence took effect)")

    # ------------------------------------------------------------------
    # Step 8: capacity plan AFTER -- the real, measurable before/after
    # ------------------------------------------------------------------
    banner("STEP 8 -- Real Phase 8 capacity plan AFTER: RIGHT_ARM's QA demand is now visible")
    plan_after = client.get("/api/v1/capacity/plan").json()
    print(f"  environment_count={plan_after['environment_count']} "
          f"(was {plan_before['environment_count']})")
    for d in plan_after["environment_demands"]:
        print(f"    {d['environment']:<12} {d['dataset_name']:<32} cadence={d['refresh_cadence_type']}")
    assert plan_after["environment_count"] == plan_before["environment_count"] + 1
    new_demand = next(
        d for d in plan_after["environment_demands"]
        if d["environment"] == "qa" and d["dataset_name"] == "right-arm-member-claims-subset"
    )
    print(f"  NEW demand confirmed: {new_demand['environment']}/{new_demand['dataset_name']} "
          f"cadence={new_demand['refresh_cadence_type']} "
          f"attributed_storage_bytes={new_demand['attributed_storage_bytes']}")
    print("  This demand was produced entirely by Phase 7/8's existing, unmodified machinery -- "
          "no parallel capacity-planning system was created for this governance layer.")

    # ------------------------------------------------------------------
    # Step 9: adversarial proof -- a request against an UNAPPROVED policy
    #         version is rejected, not silently accepted
    # ------------------------------------------------------------------
    banner("STEP 9 -- Adversarial: a consumer cannot bypass governance with an unapproved policy version")
    rogue_policy_draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(
                DEFAULT_POLICY.model_copy(update={"version": DEFAULT_POLICY.version + 1}).model_dump_json()
            ),
            "masking_engine_version": MASKING_ENGINE_VERSION,
            "created_by": "right-arm-lead@example.org",
            "notes": "RIGHT_ARM attempting to fast-track its own, unreviewed policy revision.",
        },
    ).json()
    print(f"  RIGHT_ARM drafts its OWN policy revision (status={rogue_policy_draft['approval_status']}) "
          "-- still not approved.")
    bypass_attempt = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": right["business_consumer_id"],
            "dataset_name": "right-arm-member-claims-subset",
            "environment": "sit",
            "policy_version_id": rogue_policy_draft["policy_version_id"],
            "subset_size_hint": "irrelevant -- this must be rejected",
            "refresh_cadence_type": "weekly",
            "requested_by": "right-arm-lead@example.org",
        },
    )
    print(f"  Attempt rejected: HTTP {bypass_attempt.status_code} -> {bypass_attempt.json()['detail'][:110]}...")
    assert bypass_attempt.status_code == 409

    banner("DONE -- Phase 10 centralized masking governance demo completed successfully")
    print("Summary:")
    print(f"  Governed policy: {approved_policy['policy_name']}@{approved_policy['policy_version']} "
          f"(policy_version_id={approved_policy['policy_version_id']}, status=APPROVED)")
    print(f"  LEFT_ARM and RIGHT_ARM both requested datasets referencing this exact policy_version_id.")
    print(f"  RIGHT_ARM's additional QA capacity request became real Phase 7 row "
          f"{qa_env_request_id} and is visible in real Phase 8 capacity accounting.")
    print(f"  A same-consumer attempt to use an unapproved policy version was rejected (HTTP 409).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
