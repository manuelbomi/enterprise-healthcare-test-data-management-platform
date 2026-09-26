"""Phase 11 failure-injection tests -- control-plane side.

Covers the four required scenarios that are genuinely control-plane
owned (duplicate refresh request, consumer requests a revoked dataset
-- the governance-layer angle Phase 7 itself didn't have, RBAC
rejection as this phase's own concrete "fail safely" mechanism, and a
defense-in-depth extension of Phase 6's certification-validation gate)
plus real, end-to-end proof that RBAC and audit logging are actually
wired to real mutations, not just unit-tested in isolation
(`test_platform_rbac.py`/`test_platform_audit.py`).

See `services/data-plane/tests/platform_integrity/test_failure_injection.py`
for the four data-plane-owned scenarios (masking crash, storage
unavailable, dataset corruption, schema drift, secret missing).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from healthcare_tdm_contracts import CertificationStatus
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.domain.lifecycle import LifecycleRepository
from control_plane.domain.lifecycle.scheduler import LocalRefreshOrchestrator
from control_plane.main import create_app
from control_plane.platform.dead_letter import DeadLetterStore
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
    return _client(tmp_path / "failure-injection.db")


def _register_version(client: TestClient, dataset_name: str = "tiny-fixed_population") -> dict:
    report = make_certified_report(dataset_name=dataset_name)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": dataset_name,
            "certification_report": json.loads(report.model_dump_json()),
            "storage_uri": "data/tmp/certification-run",
            "size_bytes": 123_456,
            "row_counts": {"member": 10, "claim": 42},
            "created_by": "steward@example.org",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


# ---------------------------------------------------------------------------
# Scenario: RBAC rejection (this phase's real, enforced mechanism)
# ---------------------------------------------------------------------------


def test_insufficiently_privileged_actor_is_rejected_revoking_a_dataset_version(client: TestClient) -> None:
    version = _register_version(client)

    response = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "attempted defect fix", "revoked_by": "intern@example.org"},
        headers=auth_header(client, Role.REQUESTER),
    )
    assert response.status_code == 403
    assert "requester" in response.json()["detail"]

    # The version was NOT actually revoked -- rejection happened before
    # any repository mutation was attempted.
    fetched = client.get(f"/api/v1/lifecycle/dataset-versions/{version['version_id']}")
    assert fetched.json()["status"] == "active"


def test_an_unauthenticated_caller_is_rejected_before_an_insufficiently_privileged_one_would_be(
    client: TestClient,
) -> None:
    """Phase 18A (`problems_final_review.md` P0-1, now resolved): before
    this phase, `actor_role` was a plain, unverified request-body field
    -- ANY caller could claim `PLATFORM_ADMIN` and succeed. This proves
    the real fix end to end: a request with no bearer token at all (the
    exact shape of the pre-Phase-18A live demonstration in P0-1's own
    write-up) is rejected with 401 *before* RBAC is even evaluated, and
    the dataset version is provably left untouched."""

    version = _register_version(client)
    response = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "attempted defect fix", "revoked_by": "attacker@example.org"},
    )
    assert response.status_code == 401

    fetched = client.get(f"/api/v1/lifecycle/dataset-versions/{version['version_id']}")
    assert fetched.json()["status"] == "active"


def test_a_correctly_privileged_actor_can_revoke(client: TestClient) -> None:
    version = _register_version(client)
    response = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={
            "reason": "real defect",
            "revoked_by": "compliance@example.org",
        },
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert response.status_code == 200
    assert response.json()["status"] == "revoked"


def test_insufficiently_privileged_actor_is_rejected_approving_a_policy_version(client: TestClient) -> None:
    policy = make_sample_masking_policy()
    draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(policy.model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "admin@example.org",
        },
    ).json()
    client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/submit",
        json={"performed_by": "admin@example.org"},
    )

    response = client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/approve",
        json={"performed_by": "random-consumer@example.org"},
        headers=auth_header(client, Role.REQUESTER),
    )
    assert response.status_code == 403

    fetched = client.get(f"/api/v1/governance/policy-versions/{draft['policy_version_id']}")
    assert fetched.json()["approval_status"] == "pending_approval"  # NOT approved


def test_rbac_denial_is_itself_recorded_as_an_audit_event(client: TestClient) -> None:
    version = _register_version(client)
    client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "x", "revoked_by": "intern@example.org"},
        headers=auth_header(client, Role.REQUESTER),
    )
    events = client.get("/api/v1/audit/events", params={"event_type": "access_denied"}).json()
    assert any(e["subject"] == version["version_id"] for e in events)


# ---------------------------------------------------------------------------
# Scenario: audit log is wired to real mutations
# ---------------------------------------------------------------------------


def test_registering_and_revoking_a_dataset_version_produces_real_audit_events(client: TestClient) -> None:
    version = _register_version(client)
    client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "x", "revoked_by": "sec@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )

    events = client.get(
        "/api/v1/audit/events", params={"subject": version["version_id"]}
    ).json()
    event_types = {e["event_type"] for e in events}
    assert "dataset_version_registered" in event_types
    assert "dataset_version_revoked" in event_types


# ---------------------------------------------------------------------------
# Scenario: duplicate refresh request
# ---------------------------------------------------------------------------


def test_duplicate_refresh_requests_do_not_corrupt_state(client: TestClient) -> None:
    """Calling refresh() twice in rapid succession for the same
    environment request must not create a duplicate
    `EnvironmentDatasetRequest` or a duplicate `DatasetVersion` -- only
    a second, distinct `RefreshRunRecord` log entry (correct, since
    each is a real, separate execution). See `problems_phase_07.md`
    P7-2 for the one remaining, honestly documented gap this does not
    close (concurrent *scheduler sweeps*, as opposed to duplicate calls
    to this single-request endpoint)."""

    _register_version(client, dataset_name="dup-ds")
    request = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": "dev", "dataset_name": "dup-ds", "requested_by": "a"},
    ).json()

    run_1 = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )
    run_2 = client.post(
        f"/api/v1/lifecycle/environment-requests/{request['request_id']}/refresh",
        json={"triggered_by": "a", "trigger": "on_demand"},
    )
    assert run_1.status_code == 200
    assert run_2.status_code == 200
    assert run_1.json()["run_id"] != run_2.json()["run_id"]  # two distinct, real executions

    # Exactly one EnvironmentDatasetRequest still exists for this
    # (environment, dataset_name) -- the unique constraint plus
    # request_environment's idempotency together guarantee this.
    all_requests = client.get(
        "/api/v1/lifecycle/environment-requests", params={"dataset_name": "dup-ds"}
    ).json()
    assert len(all_requests) == 1

    # No duplicate dataset version was created by refreshing twice.
    all_versions = client.get("/api/v1/lifecycle/dataset-versions", params={"dataset_name": "dup-ds"}).json()
    assert len(all_versions) == 1


def test_duplicate_dataset_version_registration_is_idempotent(client: TestClient) -> None:
    """A caller retrying `register_dataset_version` with the identical
    `CertificationReport` (e.g. after an ambiguous network timeout)
    must not create two `DatasetVersion`s. This is the real gap found
    and fixed while writing this test -- see `problems_phase_11.md`'s
    "Resolved problems" section."""

    report = make_certified_report(dataset_name="idempotency-ds")
    body = {
        "dataset_name": "idempotency-ds",
        "certification_report": json.loads(report.model_dump_json()),
        "storage_uri": "data/tmp/idempotency-run",
        "size_bytes": 999,
        "row_counts": {"member": 5},
        "created_by": "retrying-client@example.org",
    }

    first = client.post("/api/v1/lifecycle/dataset-versions", json=body)
    second = client.post("/api/v1/lifecycle/dataset-versions", json=body)  # exact retry
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["version_id"] == second.json()["version_id"]

    all_versions = client.get(
        "/api/v1/lifecycle/dataset-versions", params={"dataset_name": "idempotency-ds"}
    ).json()
    assert len(all_versions) == 1


# ---------------------------------------------------------------------------
# Scenario: consumer requests a revoked dataset (governance-layer angle)
# ---------------------------------------------------------------------------


def test_consumer_cannot_fulfill_request_against_a_dataset_whose_only_version_is_revoked(
    client: TestClient,
) -> None:
    """Phase 7 already proves revocation blocks *new selection* at the
    lifecycle layer (`test_revoke_does_not_move_an_environment_already_using_it`,
    `test_rollback_to_revoked_version_returns_409`). This test proves
    the same guarantee holds when reached through the *governance*
    layer's `fulfill_consumer_request` -- a business consumer whose
    request targets a dataset whose only registered version has since
    been revoked must be rejected the same way a direct Phase 7 caller
    would be, not bypass the protection through the governance
    integration path."""

    # Draft, submit, approve a governed policy version.
    policy = make_sample_masking_policy()
    draft = client.post(
        "/api/v1/governance/policy-versions",
        json={
            "masking_policy": json.loads(policy.model_dump_json()),
            "masking_engine_version": "1.0.0",
            "created_by": "admin@example.org",
        },
    ).json()
    client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/submit",
        json={"performed_by": "admin@example.org"},
    )
    approved = client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/approve",
        json={"performed_by": "compliance@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    ).json()

    # Register a business consumer and the ONLY dataset version.
    consumer = client.post(
        "/api/v1/governance/business-consumers",
        json={"code": "LEFT_ARM", "display_name": "Left Arm"},
    ).json()
    version = _register_version(client, dataset_name="revoked-for-consumer")

    # Revoke the only version BEFORE the consumer's request is fulfilled.
    revoke_resp = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "defect found before fulfillment", "revoked_by": "sec@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert revoke_resp.status_code == 200

    submitted = client.post(
        "/api/v1/governance/consumer-requests",
        json={
            "business_consumer_id": consumer["business_consumer_id"],
            "dataset_name": "revoked-for-consumer",
            "environment": "qa",
            "policy_version_id": approved["policy_version_id"],
            "refresh_cadence_type": "weekly",
            "requested_by": "left-arm-lead@example.org",
        },
    ).json()

    fulfill_resp = client.post(
        f"/api/v1/governance/consumer-requests/{submitted['consumer_request_id']}/fulfill",
        json={"triggered_by": "left-arm-lead@example.org"},
    )
    assert fulfill_resp.status_code == 409
    assert "ACTIVE" in fulfill_resp.json()["detail"] or "active" in fulfill_resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# Scenario: certification validation fails (Phase 6 cross-reference +
# a control-plane-layer defense-in-depth extension)
# ---------------------------------------------------------------------------


def test_a_failed_certification_report_cannot_be_registered_as_a_dataset_version(client: TestClient) -> None:
    """Phase 6 already proves a FAILED `CertificationReport` cannot be
    PUBLISHED at the data-plane state-machine layer
    (`data_plane.certification.state_machine`,
    `docs/CERTIFICATION_VS_MASKING.md`). This test proves the
    control-plane's OWN, independent layer -- `LifecycleRepository.register_dataset_version`
    -- refuses a FAILED report too, a real defense-in-depth check
    rather than the lifecycle layer blindly trusting whatever status a
    caller-supplied report claims."""

    failed_report = make_certified_report(dataset_name="never-registered", status=CertificationStatus.FAILED)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "never-registered",
            "certification_report": json.loads(failed_report.model_dump_json()),
            "storage_uri": "data/tmp/should-not-be-registered",
            "size_bytes": 1,
            "row_counts": {},
            "created_by": "attacker-or-bug@example.org",
        },
    )
    assert response.status_code == 422

    listed = client.get("/api/v1/lifecycle/dataset-versions", params={"dataset_name": "never-registered"}).json()
    assert listed == []


# ---------------------------------------------------------------------------
# Dead-letter handling: a scheduled sweep's per-request failure is
# durably recorded, not only returned to the one caller.
# ---------------------------------------------------------------------------


def test_scheduler_sweep_wires_a_real_failure_into_the_dead_letter_store(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The real, end-to-end wiring: `LocalRefreshOrchestrator.run_due_refreshes`
    itself writes to `DeadLetterStore` when a due request's refresh
    raises -- not merely `RefreshSweepResult.errors` (an in-memory dict
    visible only to the one caller of this one sweep). Forces a real
    failure the same way `test_lifecycle_repository.py` forces a
    request to be "due" (`as_of=far_future`, never editing
    `next_refresh_at` directly), then makes `LifecycleRepository.refresh`
    raise for this one request (simulating a real, unexpected failure
    mid-sweep -- e.g. a transient DB error on that one row) while
    `due_refreshes` still finds it normally."""

    import healthcare_tdm_contracts as c
    from datetime import datetime, timedelta, timezone

    engine = create_sqlite_engine(str(tmp_path / "dead-letter-sweep.db"))
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        repo = LifecycleRepository(session)
        report = make_certified_report(dataset_name="sweep-ds")
        repo.register_dataset_version(
            dataset_name="sweep-ds",
            certification_report=report,
            storage_uri="data/tmp/sweep-run",
            size_bytes=1,
            row_counts={},
            created_by="a",
        )
        request = repo.request_environment(environment=c.Environment.DEV, dataset_name="sweep-ds", requested_by="a")

        orchestrator = LocalRefreshOrchestrator(repo)
        far_future = datetime.now(timezone.utc) + timedelta(days=365)
        due = orchestrator.due_refreshes(as_of=far_future)
        assert len(due) == 1

        def _boom(*args, **kwargs):
            raise RuntimeError("simulated: transient failure refreshing this one request")

        monkeypatch.setattr(repo, "refresh", _boom)

        result = orchestrator.run_due_refreshes(as_of=far_future)
        assert str(request.request_id) in result.errors
        assert "simulated" in result.errors[str(request.request_id)]

        dead_letters = DeadLetterStore(session)
        recorded = dead_letters.list_events(event_type="scheduled_refresh_failed")
        assert any(r.subject == str(request.request_id) for r in recorded)
