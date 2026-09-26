"""Tests for `POST /api/v1/lifecycle/dataset-versions/governed` (Phase
18A, resolves `problems_final_review.md` P1-8): proves the real gap the
finding described (`register_dataset_version` never checks Phase 10
governance at all) still reproduces on the pre-existing, UNGOVERNED
endpoint -- by design, see its docstring -- and is closed on the new
GOVERNED endpoint.
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

from conftest import make_certified_report, make_sample_masking_policy


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
    return _client(tmp_path / "governed-registration.db")


def _register_body(dataset_name: str, *, policy_version: int = 1) -> dict:
    report = make_certified_report(dataset_name=dataset_name)
    payload = json.loads(report.model_dump_json())
    payload["masking_policy_version"] = policy_version
    return {
        "dataset_name": dataset_name,
        "certification_report": payload,
        "storage_uri": "data/tmp/certification-run",
        "size_bytes": 1_000,
        "row_counts": {"member": 10},
        "created_by": "steward@example.org",
    }


def _draft_and_approve_policy(client: TestClient, *, version: int = 1) -> dict:
    policy = make_sample_masking_policy(version=version)
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
    from conftest import auth_header
    from control_plane.platform.rbac import Role

    approved = client.post(
        f"/api/v1/governance/policy-versions/{draft['policy_version_id']}/approve",
        json={"performed_by": "compliance-steward@example.org"},
        headers=auth_header(client, Role.COMPLIANCE_APPROVER),
    )
    assert approved.status_code == 200, approved.text
    return approved.json()


def test_reproduction_the_ungoverned_endpoint_still_registers_without_any_governance_at_all(
    client: TestClient,
) -> None:
    """The exact gap `problems_final_review.md` P1-8 described: no
    `MaskingPolicyVersion` was ever drafted/approved for this
    dataset_name at all, yet `register_dataset_version` (the
    pre-existing, now explicitly-labeled UNGOVERNED path) still
    succeeds. This is intentional, documented behavior for that
    endpoint -- not a regression -- and is what the new governed
    endpoint below exists to provide an alternative to."""

    response = client.post("/api/v1/lifecycle/dataset-versions", json=_register_body("ungoverned-ds"))
    assert response.status_code == 201, response.text


def test_governed_registration_rejects_when_no_policy_was_ever_approved(client: TestClient) -> None:
    response = client.post(
        "/api/v1/lifecycle/dataset-versions/governed", json=_register_body("governed-ds-no-policy")
    )
    assert response.status_code == 409
    assert "No APPROVED MaskingPolicyVersion" in response.json()["detail"]


def test_governed_registration_rejects_a_masking_policy_version_mismatch(client: TestClient) -> None:
    _draft_and_approve_policy(client, version=1)
    # certification_report claims version 2, but only version 1 is approved.
    response = client.post(
        "/api/v1/lifecycle/dataset-versions/governed",
        json=_register_body("governed-ds-mismatch", policy_version=2),
    )
    assert response.status_code == 409
    assert "does not match the currently-APPROVED policy_version" in response.json()["detail"]


def test_governed_registration_succeeds_when_the_report_matches_the_approved_policy_version(
    client: TestClient,
) -> None:
    approved = _draft_and_approve_policy(client, version=1)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions/governed",
        json=_register_body("governed-ds-ok", policy_version=1),
    )
    assert response.status_code == 201, response.text
    version = response.json()
    assert version["masking_policy_version"] == 1

    events = client.get("/api/v1/audit/events", params={"subject": version["version_id"]}).json()
    registered = [e for e in events if e["event_type"] == "dataset_version_registered"]
    assert registered
    assert registered[0]["detail"]["governed"] == "true"
    assert registered[0]["detail"]["approved_policy_version_id"] == approved["policy_version_id"]


# ----------------------------------------------------------------------
# Phase 18B (`problems_final_review.md` P2-4): independently re-derived
# row_counts, for the entities the certification report's own
# row_count_reconciliation trail covers
# ----------------------------------------------------------------------


def test_governed_registration_rejects_a_row_counts_claim_that_contradicts_the_reports_own_trail(
    client: TestClient,
) -> None:
    """`make_certified_report`'s `row_count_reconciliation` says
    `"member": "source=26 selected=10 final=10"` -- a caller claiming
    `row_counts={"member": 999}` (contradicting the certification
    pipeline's own measured final count) must be refused, not silently
    trusted."""

    _draft_and_approve_policy(client, version=1)
    body = _register_body("governed-ds-row-count-mismatch", policy_version=1)
    body["row_counts"] = {"member": 999}

    response = client.post("/api/v1/lifecycle/dataset-versions/governed", json=body)
    assert response.status_code == 409
    assert "row_counts does not match the certification report's own" in response.json()["detail"]
    assert "'member': (999, 10)" in response.json()["detail"]


def test_governed_registration_succeeds_when_row_counts_matches_the_reports_own_trail(
    client: TestClient,
) -> None:
    """The positive case: `row_counts={"member": 10}` agrees with the
    report's own `final=10` for `member`, so registration is not
    refused -- this is the same `_register_body` default every other
    passing test in this file already relies on, made explicit here as
    its own dedicated proof of the new re-derivation check."""

    _draft_and_approve_policy(client, version=1)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions/governed",
        json=_register_body("governed-ds-row-count-match", policy_version=1),
    )
    assert response.status_code == 201, response.text


def test_governed_registration_does_not_check_entities_absent_from_the_reports_own_trail(
    client: TestClient,
) -> None:
    """`row_count_reconciliation` only covers `member` in this fixture
    -- a caller-supplied `row_counts["claim"]` has nothing to be
    cross-checked against, so it is accepted as-is (this function never
    invents a count it cannot actually read back out of the report; see
    `_independently_derived_row_counts`'s own docstring). Not a full fix
    for P2-4 (this is exactly the documented remaining gap for entities/
    fields the report's own trail does not cover, e.g. `size_bytes`
    entirely), but a real, proportionate narrowing of it."""

    _draft_and_approve_policy(client, version=1)
    body = _register_body("governed-ds-untracked-entity", policy_version=1)
    body["row_counts"]["claim"] = 999_999  # not present in row_count_reconciliation at all

    response = client.post("/api/v1/lifecycle/dataset-versions/governed", json=body)
    assert response.status_code == 201, response.text
