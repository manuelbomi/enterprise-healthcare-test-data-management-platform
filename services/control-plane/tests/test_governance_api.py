"""Tests for the centralized masking governance API (`api/v1/governance.py`,
Phase 10), exercised through a real FastAPI `TestClient` with
`get_db_session` overridden to point at a fresh temporary SQLite file per
test -- the same dependency-override pattern `test_lifecycle_api.py` and
`test_capacity_api.py` use, confirming all three routers share one
database/session per test.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app
from control_plane.platform.rbac import Role

from conftest import auth_header, make_certified_report, make_sample_masking_policy


def _client(db_path: Path) -> TestClient:
    engine = create_sqlite_engine(str(db_path))
    factory = build_session_factory(engine)

    def _override() -> Iterator[Session]:
        with session_scope(factory) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return _client(tmp_path / "governance.db")


def _draft_and_approve_policy(client: TestClient, *, version: int = 1) -> dict:
    policy = make_sample_masking_policy(version=version)
    draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(policy.model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "governance-admin@example.org",
        },
    )
    assert draft.status_code == 201, draft.text
    policy_version_id = draft.json()["policy_version_id"]

    submitted = client.post(
        f"/api/v1/governance/policy-versions/{policy_version_id}/submit",
        json={"performed_by": "governance-admin@example.org"},
    )
    assert submitted.status_code == 200, submitted.text

    approved = client.post(
        f"/api/v1/governance/policy-versions/{policy_version_id}/approve",
        json={
            "performed_by": "compliance-steward@example.org",
            "comments": "Approved.",
        },
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["approval_status"] == "approved"
    return approved.json()


def _register_consumer(client: TestClient, code: str, display_name: str) -> dict:
    response = client.post(
        "/api/v1/governance/business-consumers",
        json={"code": code, "display_name": display_name},
    )
    assert response.status_code == 201, response.text
    return response.json()


def _register_dataset_version(client: TestClient, dataset_name: str) -> dict:
    report = make_certified_report(dataset_name=dataset_name)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": dataset_name,
            "certification_report": json.loads(report.model_dump_json()),
            "storage_uri": f"data/tmp/{dataset_name}-run",
            "size_bytes": 10_000,
            "row_counts": {"member": 10, "claim": 40},
            "created_by": "platform@example.org",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_policy_version_approval_workflow(client: TestClient) -> None:
    approved = _draft_and_approve_policy(client)
    approvals = client.get(f"/api/v1/governance/policy-versions/{approved['policy_version_id']}/approvals")
    assert approvals.status_code == 200
    assert [a["status"] for a in approvals.json()] == ["pending_approval", "approved"]

    fetched = client.get("/api/v1/governance/policy-versions/approved/phase3-default")
    assert fetched.status_code == 200
    assert fetched.json()["policy_version_id"] == approved["policy_version_id"]


def test_approve_and_reject_policy_version_audit_events_record_the_verified_identity_not_free_text(
    client: TestClient,
) -> None:
    """Phase 18B (`problems_final_review.md` P2-13): `approve_policy_version`/
    `reject_policy_version` already require a verified bearer-token
    identity (`Depends(get_current_actor)`) for RBAC -- this proves the
    audit trail's own `actor` field now uses that verified identity
    (`demo.compliance_approver`, the seeded login username) rather than
    the unverified `performed_by` free text (`compliance-steward@example.org`)
    the request body separately carries."""

    from conftest import auth_header
    from control_plane.platform.rbac import Role

    policy = make_sample_masking_policy(version=1)
    draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(policy.model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "governance-admin@example.org",
        },
    ).json()
    client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/submit",
        json={"performed_by": "governance-admin@example.org"},
    )

    approved = client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/approve",
        json={"performed_by": "compliance-steward@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert approved.status_code == 200, approved.text

    events = client.get(
        "/api/v1/audit/events",
        params={"event_type": "policy_approved", "subject": draft["policy_version_id"]},
    ).json()
    assert len(events) == 1
    assert events[0]["actor"] == "demo.compliance_approver"
    assert events[0]["detail"]["performed_by"] == "compliance-steward@example.org"

    # Same proof for reject_policy_version, against a second draft.
    draft2 = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(make_sample_masking_policy(version=2).model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "governance-admin@example.org",
        },
    ).json()
    client.post(
        f"/api/v1/governance/policy-versions/{draft2['policy_version_id']}/submit",
        json={"performed_by": "governance-admin@example.org"},
    )
    rejected = client.post(
        f"/api/v1/governance/policy-versions/{draft2['policy_version_id']}/reject",
        json={"performed_by": "another-steward@example.org", "comments": "does not meet B.2 requirements"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert rejected.status_code == 200, rejected.text

    reject_events = client.get(
        "/api/v1/audit/events",
        params={"event_type": "policy_rejected", "subject": draft2["policy_version_id"]},
    ).json()
    assert len(reject_events) == 1
    assert reject_events[0]["actor"] == "demo.compliance_approver"
    assert reject_events[0]["detail"]["performed_by"] == "another-steward@example.org"


def test_cannot_approve_a_draft_policy_version(client: TestClient) -> None:
    policy = make_sample_masking_policy()
    draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(policy.model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "admin@example.org",
        },
    ).json()
    response = client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/approve",
        json={"performed_by": "reviewer@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert response.status_code == 409


def test_business_consumer_duplicate_code_returns_409(client: TestClient) -> None:
    _register_consumer(client, "LEFT_ARM", "Left Arm")
    response = client.post(
        "/api/v1/governance/business-consumers", json={"code": "LEFT_ARM", "display_name": "Left Arm Again"}
    )
    assert response.status_code == 409


def test_consumer_request_rejected_without_approved_policy(client: TestClient) -> None:
    consumer = _register_consumer(client, "LEFT_ARM", "Left Arm")
    policy = make_sample_masking_policy()
    draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(policy.model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "admin@example.org",
        },
    ).json()

    response = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": consumer["business_consumer_id"],
            "dataset_name": "left-arm-member-claims-subset",
            "environment": "dev",
            "policy_version_id": draft["policy_version_id"],
            "subset_size_hint": "1% of members",
            "refresh_cadence_type": "weekly",
            "requested_by": "left-arm-lead@example.org",
        },
    )
    assert response.status_code == 409


def test_both_arms_use_the_same_approved_policy_version_end_to_end(client: TestClient) -> None:
    """The Phase 10 headline API-level proof: LEFT_ARM and RIGHT_ARM each
    submit a `ConsumerDatasetRequest` for their own dataset/environment/
    subset size/cadence, both referencing the same approved
    `MaskingPolicyVersion`, and both are fulfilled into real Phase 7
    `EnvironmentDatasetRequest`s."""

    approved = _draft_and_approve_policy(client)
    left = _register_consumer(client, "LEFT_ARM", "Left Arm Business Unit")
    right = _register_consumer(client, "RIGHT_ARM", "Right Arm Business Unit")

    _register_dataset_version(client, "left-arm-member-claims-subset")
    _register_dataset_version(client, "right-arm-member-claims-subset")

    left_request = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": left["business_consumer_id"],
            "dataset_name": "left-arm-member-claims-subset",
            "environment": "dev",
            "policy_version_id": approved["policy_version_id"],
            "subset_size_hint": "1% of members",
            "refresh_cadence_type": "weekly",
            "requested_by": "left-arm-lead@example.org",
        },
    )
    assert left_request.status_code == 201, left_request.text

    right_request = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": right["business_consumer_id"],
            "dataset_name": "right-arm-member-claims-subset",
            "environment": "qa",
            "policy_version_id": approved["policy_version_id"],
            "subset_size_hint": "8% of members, regression set",
            "refresh_cadence_type": "biweekly",
            "performance_requirements": "sub-200ms p95",
            "requested_by": "right-arm-lead@example.org",
        },
    )
    assert right_request.status_code == 201, right_request.text

    assert (
        left_request.json()["policy_version_id"]
        == right_request.json()["policy_version_id"]
        == approved["policy_version_id"]
    )

    left_fulfilled = client.post(
        f"/api/v1/governance/consumer-requests/{left_request.json()['consumer_request_id']}/fulfill",
        json={"triggered_by": "governance-service"},
    )
    right_fulfilled = client.post(
        f"/api/v1/governance/consumer-requests/{right_request.json()['consumer_request_id']}/fulfill",
        json={"triggered_by": "governance-service"},
    )
    assert left_fulfilled.status_code == 200, left_fulfilled.text
    assert right_fulfilled.status_code == 200, right_fulfilled.text
    assert left_fulfilled.json()["environment_request_id"] is not None
    assert right_fulfilled.json()["environment_request_id"] is not None

    # Confirm both fulfillments are real Phase 7 rows, visible via the
    # unmodified Phase 7 lifecycle API.
    env_requests = client.get("/api/v1/lifecycle/environment-requests").json()
    consumers_seen = {r["consumer"] for r in env_requests}
    assert {"LEFT_ARM", "RIGHT_ARM"} <= consumers_seen

    # And real Phase 8 capacity accounting picks both up with no
    # governance-specific capacity endpoint of its own.
    plan = client.get("/api/v1/capacity/plan").json()
    assert plan["environment_count"] == 2


# ----------------------------------------------------------------------
# Phase 18B (`problems_final_review.md` P3-4): REJECTED/CANCELLED
# terminal states, exercised through the real API
# ----------------------------------------------------------------------


def _submit_request(client: TestClient, *, consumer: dict, policy_version_id: str, dataset_name: str) -> dict:
    response = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": consumer["business_consumer_id"],
            "dataset_name": dataset_name,
            "environment": "dev",
            "policy_version_id": policy_version_id,
            "subset_size_hint": "1% of members",
            "refresh_cadence_type": "weekly",
            "requested_by": "left-arm-lead@example.org",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_reject_consumer_request_returns_terminal_status_and_reason(client: TestClient) -> None:
    approved = _draft_and_approve_policy(client)
    consumer = _register_consumer(client, "LEFT_ARM", "Left Arm Business Unit")
    _register_dataset_version(client, "left-arm-member-claims-subset")
    submitted = _submit_request(
        client,
        consumer=consumer,
        policy_version_id=approved["policy_version_id"],
        dataset_name="left-arm-member-claims-subset",
    )

    rejected = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/reject",
        json={"performed_by": "platform-admin@example.org", "reason": "not appropriate for this consumer"},
    )
    assert rejected.status_code == 200, rejected.text
    body = rejected.json()
    assert body["status"] == "rejected"
    assert "platform-admin@example.org" in body["resolution_notes"]
    assert "not appropriate for this consumer" in body["resolution_notes"]

    # Terminal: a second reject, a cancel, or a fulfill against the same
    # already-resolved request is refused with 409, not silently allowed.
    second_reject = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/reject",
        json={"performed_by": "someone-else@example.org"},
    )
    assert second_reject.status_code == 409
    cancel_after_reject = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/cancel",
        json={"performed_by": "someone-else@example.org"},
    )
    assert cancel_after_reject.status_code == 409
    fulfill_after_reject = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/fulfill",
        json={"triggered_by": "governance-service"},
    )
    assert fulfill_after_reject.status_code == 409


def test_cancel_consumer_request_returns_terminal_status_and_reason(client: TestClient) -> None:
    approved = _draft_and_approve_policy(client)
    consumer = _register_consumer(client, "RIGHT_ARM", "Right Arm Business Unit")
    _register_dataset_version(client, "right-arm-member-claims-subset")
    submitted = _submit_request(
        client,
        consumer=consumer,
        policy_version_id=approved["policy_version_id"],
        dataset_name="right-arm-member-claims-subset",
    )

    cancelled = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/cancel",
        json={"performed_by": "right-arm-lead@example.org", "reason": "business need went away"},
    )
    assert cancelled.status_code == 200, cancelled.text
    assert cancelled.json()["status"] == "cancelled"
    assert "business need went away" in cancelled.json()["resolution_notes"]

    fulfill_after_cancel = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/fulfill",
        json={"triggered_by": "governance-service"},
    )
    assert fulfill_after_cancel.status_code == 409
