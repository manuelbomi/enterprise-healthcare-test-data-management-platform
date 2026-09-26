"""Tests for the dataset lifecycle API (`api/v1/lifecycle.py`), exercised
through a real FastAPI `TestClient` with `get_db_session` overridden to
point at a fresh temporary SQLite file per test -- the same
dependency-override pattern `test_catalog_api.py` uses for
`get_catalog_repository`.
"""

from __future__ import annotations

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

from conftest import auth_header, make_certified_report


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
    return _client(tmp_path / "lifecycle.db")


def _register_version(client: TestClient, dataset_name: str = "tiny-fixed_population") -> dict:
    report = make_certified_report(dataset_name=dataset_name)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": dataset_name,
            "certification_report": __import__("json").loads(report.model_dump_json()),
            "storage_uri": "data/tmp/certification-run",
            "size_bytes": 123_456,
            "row_counts": {"member": 10, "claim": 42},
            "created_by": "steward@example.org",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_register_dataset_version(client: TestClient) -> None:
    body = _register_version(client)
    assert body["version_number"] == 1
    assert body["status"] == "active"


def test_register_rejects_non_certified_report(client: TestClient) -> None:
    report = make_certified_report()
    payload = __import__("json").loads(report.model_dump_json())
    payload["status"] = "draft"
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "ds",
            "certification_report": payload,
            "storage_uri": "uri",
            "size_bytes": 1,
            "row_counts": {},
            "created_by": "a",
        },
    )
    assert response.status_code == 422


def test_list_and_get_dataset_version(client: TestClient) -> None:
    created = _register_version(client)
    listed = client.get("/api/v1/lifecycle/dataset-versions").json()
    assert len(listed) == 1

    fetched = client.get(f"/api/v1/lifecycle/dataset-versions/{created['version_id']}")
    assert fetched.status_code == 200
    assert fetched.json()["version_id"] == created["version_id"]


def test_get_missing_dataset_version_404s(client: TestClient) -> None:
    response = client.get("/api/v1/lifecycle/dataset-versions/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_request_two_environments_share_one_version(client: TestClient) -> None:
    version = _register_version(client, dataset_name="ds")

    dev = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a", "consumer": "claims-dev-team"},
    )
    qa = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "qa", "dataset_name": "ds", "requested_by": "b", "consumer": "claims-qa-team"},
    )
    assert dev.status_code == 201
    assert qa.status_code == 201
    assert dev.json()["current_version_id"] == version["version_id"]
    assert qa.json()["current_version_id"] == version["version_id"]

    refreshed_version = client.get(f"/api/v1/lifecycle/dataset-versions/{version['version_id']}").json()
    assert set(refreshed_version["referenced_by_environments"]) == {"dev", "qa"}


def test_request_environment_without_active_version_returns_409(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "nonexistent", "requested_by": "a"},
    )
    assert response.status_code == 409


def test_refresh_policies_for_all_five_environments(client: TestClient) -> None:
    expected = {
        "dev": "weekly",
        "qa": "weekly",
        "sit": "biweekly",
        "uat": "release_driven",
        "performance": "monthly",
    }
    for env, cadence in expected.items():
        response = client.get(f"/api/v1/lifecycle/refresh-policies/{env}/default")
        assert response.status_code == 200
        assert response.json()["cadence_type"] == cadence


def test_upsert_refresh_policy(client: TestClient) -> None:
    response = client.put(
        "/api/v1/lifecycle/refresh-policies",
        json={
            "environment": "performance",
            "dataset_name": None,
            "cadence_type": "monthly",
            "interval_days": 30,
            "retention_days": 60,
            "grace_period_days": 5,
            "on_demand_allowed": True,
        },
    )
    assert response.status_code == 200
    assert response.json()["policy_version"] == 1

    updated = client.put(
        "/api/v1/lifecycle/refresh-policies",
        json={
            "environment": "performance",
            "dataset_name": None,
            "cadence_type": "monthly",
            "interval_days": 45,
            "retention_days": 60,
            "grace_period_days": 5,
            "on_demand_allowed": True,
        },
    )
    assert updated.json()["policy_version"] == 2
    assert updated.json()["interval_days"] == 45


def test_on_demand_refresh_endpoint(client: TestClient) -> None:
    _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    ).json()

    response = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "qa-engineer", "trigger": "on_demand"},
    )
    assert response.status_code == 200
    assert response.json()["succeeded"] is True


def test_on_demand_refresh_rejected_for_release_driven_when_disallowed(client: TestClient) -> None:
    client.put(
        "/api/v1/lifecycle/refresh-policies",
        json={
            "environment": "uat",
            "dataset_name": None,
            "cadence_type": "release_driven",
            "interval_days": None,
            "retention_days": 90,
            "grace_period_days": 3,
            "on_demand_allowed": False,
        },
    )
    _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "uat", "dataset_name": "ds", "requested_by": "a"},
    ).json()

    response = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )
    assert response.status_code == 409


def test_rollback_endpoint(client: TestClient) -> None:
    _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    ).json()
    _register_version(client, dataset_name="ds")  # v2
    client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )

    response = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/rollback",
        json={
            "to_version_number": 1,
            "performed_by": "oncall@example.org",
            "reason": "v2 broke the build",
        },
        headers=auth_header(client, Role.DATA_STEWARD),
    )
    assert response.status_code == 200
    body = response.json()
    assert body["to_version_number"] == 1
    assert body["from_version_number"] == 2

    updated_request = client.get(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}"
    ).json()
    assert updated_request["current_version_number"] == 1


def test_rollback_to_revoked_version_returns_409(client: TestClient) -> None:
    v1 = _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    ).json()
    _register_version(client, dataset_name="ds")  # v2
    client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )
    client.post(
        f"/api/v1/lifecycle/dataset-versions/{v1['version_id']}/revoke",
        json={"reason": "known defect", "revoked_by": "security@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )

    response = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/rollback",
        json={"to_version_number": 1, "performed_by": "a", "reason": "try anyway"},
        headers=auth_header(client, Role.DATA_STEWARD),
    )
    assert response.status_code == 409


def test_revoke_dataset_version_endpoint(client: TestClient) -> None:
    version = _register_version(client, dataset_name="ds")
    response = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={
            "reason": "policy defect discovered",
            "revoked_by": "security@example.org",
        },
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"

    # Revoking again is rejected (terminal state).
    again = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "again", "revoked_by": "security@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert again.status_code == 409

    # No ACTIVE version left -> a new environment request 409s.
    blocked = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    )
    assert blocked.status_code == 409


def test_revoke_and_rollback_audit_events_record_the_verified_identity_not_free_text(
    client: TestClient,
) -> None:
    """Phase 18B (`docs/problems/problems_final_review.md` P2-13): `revoke_dataset_version`/
    `rollback_environment_request` already require a verified
    bearer-token identity for RBAC -- this proves the audit trail's own
    `actor` field now uses that verified identity (the seeded login
    username), not the unverified `revoked_by`/`performed_by` free text
    the request body separately carries."""

    v1 = _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    ).json()
    _register_version(client, dataset_name="ds")  # v2
    client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )

    rollback = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/rollback",
        json={"to_version_number": 1, "performed_by": "oncall@example.org", "reason": "v2 broke the build"},
        headers=auth_header(client, Role.DATA_STEWARD),
    )
    assert rollback.status_code == 200, rollback.text

    rollback_events = client.get(
        "/api/v1/audit/events",
        params={"event_type": "dataset_version_rolled_back", "subject": request["request_id"]},
    ).json()
    assert len(rollback_events) == 1
    assert rollback_events[0]["actor"] == "demo.data_steward"
    assert rollback_events[0]["detail"]["performed_by"] == "oncall@example.org"

    revoke = client.post(
        f"/api/v1/lifecycle/dataset-versions/{v1['version_id']}/revoke",
        json={"reason": "policy defect discovered", "revoked_by": "security@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert revoke.status_code == 200, revoke.text

    revoke_events = client.get(
        "/api/v1/audit/events",
        params={"event_type": "dataset_version_revoked", "subject": v1["version_id"]},
    ).json()
    assert len(revoke_events) == 1
    assert revoke_events[0]["actor"] == "demo.compliance_approver"
    assert revoke_events[0]["detail"]["revoked_by"] == "security@example.org"


def test_scheduler_due_endpoint_lists_and_runs_due_refreshes(client: TestClient) -> None:
    _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    ).json()

    not_due = client.get("/api/v1/lifecycle/scheduler/due").json()
    assert request["request_id"] not in {r["request_id"] for r in not_due}

    from datetime import datetime, timedelta, timezone

    far_future = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()
    due = client.get("/api/v1/lifecycle/scheduler/due", params={"as_of": far_future}).json()
    assert request["request_id"] in {r["request_id"] for r in due}

    # Phase 18A (P1-2): this endpoint now requires a verified
    # PLATFORM_ADMIN bearer token -- an unauthenticated call is rejected
    # before any repository mutation is attempted.
    unauthenticated = client.post("/api/v1/lifecycle/scheduler/run-due", params={"as_of": far_future})
    assert unauthenticated.status_code == 401

    insufficiently_privileged = client.post(
        "/api/v1/lifecycle/scheduler/run-due",
        params={"as_of": far_future},
        headers=auth_header(client, Role.DATA_STEWARD),
    )
    assert insufficiently_privileged.status_code == 403

    swept = client.post(
        "/api/v1/lifecycle/scheduler/run-due",
        params={"as_of": far_future},
        headers=auth_header(client, Role.PLATFORM_ADMIN),
    )
    assert swept.status_code == 200
    body = swept.json()
    assert body["succeeded_count"] == 1
    assert body["failed_count"] == 0


def test_run_due_refreshes_is_refused_while_another_sweep_holds_the_lock(
    client: TestClient, tmp_path: Path
) -> None:
    """`docs/problems/problems_final_review.md` P2-2, now resolved: a second,
    overlapping `POST /scheduler/run-due` call must not be allowed to
    race the first -- it is refused with 409, not silently duplicated
    or silently allowed to interleave."""

    from datetime import datetime, timedelta, timezone

    from control_plane.db.models import SchedulerLockRow, create_sqlite_engine
    from control_plane.db.session import build_session_factory
    from control_plane.platform.scheduler_lock import LIFECYCLE_SCHEDULER_SWEEP_LOCK

    _register_version(client, dataset_name="ds")
    client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    )
    far_future = (datetime.now(timezone.utc) + timedelta(days=400)).isoformat()

    # Simulate an already-in-progress sweep by taking the lock directly
    # against the same on-disk database `client` points at, exactly the
    # way a real overlapping second `run-due` caller would find it held.
    engine = create_sqlite_engine(str(tmp_path / "lifecycle.db"))
    factory = build_session_factory(engine)
    holder_session = factory()
    holder_session.add(
        SchedulerLockRow(
            lock_name=LIFECYCLE_SCHEDULER_SWEEP_LOCK,
            acquired_by="another-sweep-in-progress",
            acquired_at=datetime.now(timezone.utc),
        )
    )
    holder_session.commit()

    refused = client.post(
        "/api/v1/lifecycle/scheduler/run-due",
        params={"as_of": far_future},
        headers=auth_header(client, Role.PLATFORM_ADMIN),
    )
    assert refused.status_code == 409
    assert "another-sweep-in-progress" in refused.text

    # Release the lock (simulating the first sweep finishing) -- the
    # next call succeeds normally.
    holder_session.query(SchedulerLockRow).filter(
        SchedulerLockRow.lock_name == LIFECYCLE_SCHEDULER_SWEEP_LOCK
    ).delete()
    holder_session.commit()
    holder_session.close()

    swept = client.post(
        "/api/v1/lifecycle/scheduler/run-due",
        params={"as_of": far_future},
        headers=auth_header(client, Role.PLATFORM_ADMIN),
    )
    assert swept.status_code == 200


# ----------------------------------------------------------------------
# Phase 13: dataset version access recording + refresh/rollback history
# ----------------------------------------------------------------------


def test_record_dataset_version_access_appends_an_audit_event(client: TestClient) -> None:
    version = _register_version(client, dataset_name="ds")

    response = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/access",
        json={"accessed_by": "qa-engineer@example.org", "environment": "qa", "purpose": "QA smoke test"},
    )
    assert response.status_code == 200
    assert response.json()["version_id"] == version["version_id"]

    events = client.get(
        "/api/v1/audit/events",
        params={"event_type": "dataset_version_accessed", "subject": version["version_id"]},
    ).json()
    assert len(events) == 1
    assert events[0]["actor"] == "qa-engineer@example.org"
    assert events[0]["detail"]["purpose"] == "QA smoke test"


def test_record_access_for_missing_version_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lifecycle/dataset-versions/00000000-0000-0000-0000-000000000000/access",
        json={"accessed_by": "qa-engineer@example.org"},
    )
    assert response.status_code == 404


def test_list_refresh_runs_and_rollback_events(client: TestClient) -> None:
    v1 = _register_version(client, dataset_name="ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "ds", "requested_by": "a"},
    ).json()
    _register_version(client, dataset_name="ds")  # v2
    client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )
    client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/rollback",
        json={
            "to_version_number": 1,
            "performed_by": "oncall@example.org",
            "reason": "v2 broke the build",
        },
        headers=auth_header(client, Role.DATA_STEWARD),
    )

    refresh_runs = client.get("/api/v1/lifecycle/refresh-runs", params={"dataset_name": "ds"}).json()
    assert len(refresh_runs) == 1
    assert refresh_runs[0]["resulting_version_id"] is not None

    rollback_events = client.get("/api/v1/lifecycle/rollback-events", params={"dataset_name": "ds"}).json()
    assert len(rollback_events) == 1
    assert rollback_events[0]["to_version_number"] == 1
    assert rollback_events[0]["to_version_id"] == v1["version_id"]
    assert rollback_events[0]["from_version_number"] == 2
    assert rollback_events[0]["reason"] == "v2 broke the build"

    scoped = client.get(
        "/api/v1/lifecycle/refresh-runs", params={"request_id": request["request_id"]}
    ).json()
    assert len(scoped) == 1
