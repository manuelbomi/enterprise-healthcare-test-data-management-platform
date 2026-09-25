"""Tests for `control_plane.domain.evidence.EvidenceRepository` (Phase
13) against a real (SQLite-backed) session -- no mocking of the
database layer, mirroring `test_lifecycle_repository.py`/
`test_governance_repository.py`'s convention exactly.

These are data-quality-style tests, not signature tests: they build a
real registered dataset version, a real governed masking policy
version, a real environment request, a real consumer request, a real
refresh, and a real rollback, then assert the resulting
`AuditEvidencePackage` actually contains the right data pulled from
each of those real rows -- not just that the method returns without
raising.
"""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from healthcare_tdm_contracts import (
    AuditEventType,
    DatasetVersionStatus,
    Environment,
    PolicyApprovalStatus,
    RefreshCadenceType,
    RefreshTrigger,
)
from sqlalchemy.orm import Session

from control_plane.catalog import CatalogRepository
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory
from control_plane.domain.evidence import EvidenceRepository, compute_bundle_checksum, verify_bundle_checksum
from control_plane.domain.governance import GovernanceRepository
from control_plane.domain.lifecycle import DatasetVersionNotFoundError, LifecycleRepository
from control_plane.platform.audit import AuditLogRepository

from conftest import make_certified_report, make_sample_masking_policy


@pytest.fixture
def session(tmp_path: Path) -> Session:
    engine = create_sqlite_engine(str(tmp_path / "evidence.db"))
    factory = build_session_factory(engine)
    with factory() as s:
        yield s


@pytest.fixture
def evidence_repo(session: Session, sample_catalog_path: Path) -> EvidenceRepository:
    return EvidenceRepository(session, catalog_repository=CatalogRepository(sample_catalog_path))


def _fully_wired_scenario(session: Session, *, dataset_name: str = "member"):
    """Build a realistic, fully-wired scenario: a registered dataset
    version, an approved masking policy version covering it, an
    environment request, a business consumer + fulfilled consumer
    request, one refresh, and one rollback to a second version. Returns
    the key objects a test needs to assert against.

    This calls the domain repositories directly (not the HTTP API), so
    it also records the same audit events `api/v1/lifecycle.py`/
    `api/v1/governance.py`'s route handlers would record as a side
    effect of each call -- those audit writes live at the API layer,
    not inside the repositories themselves (see
    `control_plane.platform.audit`'s module docstring), so a test that
    only calls repositories directly must reproduce them explicitly to
    faithfully exercise `EvidenceRepository`'s audit-trail aggregation.
    """

    lifecycle = LifecycleRepository(session)
    governance = GovernanceRepository(session)
    audit = AuditLogRepository(session)

    report_v1 = make_certified_report(dataset_name=dataset_name)
    version_1 = lifecycle.register_dataset_version(
        dataset_name=dataset_name,
        certification_report=report_v1,
        storage_uri="s3://tdm-bucket/member/v1",
        size_bytes=1_000,
        row_counts={"member": 26},
        created_by="pipeline@example.org",
    )
    audit.record(
        event_type=AuditEventType.DATASET_VERSION_REGISTERED,
        actor="pipeline@example.org",
        subject=str(version_1.version_id),
        outcome="allowed",
        detail={"dataset_name": dataset_name, "version_number": str(version_1.version_number)},
    )

    policy = make_sample_masking_policy(version=1)
    policy_version = governance.draft_policy_version(
        masking_policy=policy, masking_engine_version="1.0.0", created_by="governance-admin@example.org"
    )
    governance.submit_policy_version_for_approval(
        policy_version.policy_version_id, performed_by="governance-admin@example.org"
    )
    approved_policy_version = governance.approve_policy_version(
        policy_version.policy_version_id, performed_by="compliance@example.org", comments="Looks good."
    )
    audit.record(
        event_type=AuditEventType.POLICY_APPROVED,
        actor="compliance@example.org",
        subject=str(approved_policy_version.policy_version_id),
        outcome="allowed",
        detail={"comments": "Looks good."},
    )

    consumer = governance.register_business_consumer(code="LEFT_ARM", display_name="Left Arm")
    consumer_request = governance.submit_consumer_request(
        business_consumer_id=consumer.business_consumer_id,
        dataset_name=dataset_name,
        environment=Environment.QA,
        policy_version_id=approved_policy_version.policy_version_id,
        subset_size_hint="10%",
        refresh_cadence_type=RefreshCadenceType.WEEKLY,
        requested_by="left-arm-lead@example.org",
    )
    audit.record(
        event_type=AuditEventType.CONSUMER_REQUEST_SUBMITTED,
        actor="left-arm-lead@example.org",
        subject=str(consumer_request.consumer_request_id),
        outcome="allowed",
        detail={"dataset_name": dataset_name, "environment": Environment.QA.value},
    )
    fulfilled_request = governance.fulfill_consumer_request(
        consumer_request.consumer_request_id, triggered_by="governance-service"
    )
    audit.record(
        event_type=AuditEventType.CONSUMER_REQUEST_FULFILLED,
        actor="governance-service",
        subject=str(fulfilled_request.consumer_request_id),
        outcome="allowed",
        detail={"environment_request_id": str(fulfilled_request.environment_request_id)},
    )

    # A second, later version to refresh/rollback against.
    report_v2 = make_certified_report(dataset_name=dataset_name)
    version_2 = lifecycle.register_dataset_version(
        dataset_name=dataset_name,
        certification_report=report_v2,
        storage_uri="s3://tdm-bucket/member/v2",
        size_bytes=1_200,
        row_counts={"member": 30},
        created_by="pipeline@example.org",
    )
    audit.record(
        event_type=AuditEventType.DATASET_VERSION_REGISTERED,
        actor="pipeline@example.org",
        subject=str(version_2.version_id),
        outcome="allowed",
        detail={"dataset_name": dataset_name, "version_number": str(version_2.version_number)},
    )

    refresh_run = lifecycle.refresh(
        fulfilled_request.environment_request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="qa-lead@example.org"
    )
    audit.record(
        event_type=AuditEventType.REFRESH_EXECUTED,
        actor="qa-lead@example.org",
        subject=str(fulfilled_request.environment_request_id),
        outcome="allowed" if refresh_run.succeeded else "failed",
        detail={"trigger": RefreshTrigger.ON_DEMAND.value, "run_id": str(refresh_run.run_id)},
    )
    rollback_record = lifecycle.rollback(
        fulfilled_request.environment_request_id,
        to_version_number=version_1.version_number,
        performed_by="qa-lead@example.org",
        reason="v2 regressed a downstream test suite.",
    )
    audit.record(
        event_type=AuditEventType.DATASET_VERSION_ROLLED_BACK,
        actor="qa-lead@example.org",
        subject=str(fulfilled_request.environment_request_id),
        outcome="allowed",
        detail={"to_version_number": str(version_1.version_number)},
    )

    return {
        "version_1": version_1,
        "version_2": version_2,
        "policy_version": approved_policy_version,
        "consumer_request": fulfilled_request,
        "refresh_run": refresh_run,
        "rollback_record": rollback_record,
    }


# ----------------------------------------------------------------------
# Core aggregation correctness
# ----------------------------------------------------------------------


def test_evidence_package_aggregates_real_dataset_manifest_and_provisioning(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.dataset_version_id == version_1.version_id
    assert package.dataset_name == "member"
    assert package.dataset_manifest.version_id == version_1.version_id
    # version_1 was rolled back to and is ACTIVE again (see rollback()'s
    # "TO version was ROLLED_BACK -> ACTIVE again" transition).
    assert package.dataset_manifest.status is DatasetVersionStatus.ACTIVE

    # "who requested it" / "where provisioned"
    assert len(package.environment_requests) == 1
    assert package.environment_requests[0].environment is Environment.QA
    assert len(package.consumer_requests) == 1
    assert package.consumer_requests[0].requested_by == "left-arm-lead@example.org"


def test_evidence_package_includes_masking_policy_version_and_approvals(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.masking_policy_version is not None
    assert package.masking_policy_version.policy_name == "phase3-default"
    assert package.masking_policy_version.approval_status is PolicyApprovalStatus.APPROVED
    approval_statuses = {a.status for a in package.masking_policy_approvals}
    assert PolicyApprovalStatus.APPROVED in approval_statuses
    assert PolicyApprovalStatus.PENDING_APPROVAL in approval_statuses


def test_evidence_package_includes_classification_summary_for_dataset(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    # sample_catalog_path (conftest) has two "member" columns: ssn
    # (direct_identifier) and date_of_birth (quasi_identifier).
    scenario = _fully_wired_scenario(session, dataset_name="member")
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.classification_summary["column_count"] == 2
    assert package.classification_summary["by_category"]["direct_identifier"] == 1
    assert package.classification_summary["by_category"]["quasi_identifier"] == 1


def test_evidence_package_notes_when_no_catalog_entries_match_dataset(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session, dataset_name="some-unclassified-dataset")
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.classification_summary["column_count"] == 0
    assert any("No catalog entries found" in note for note in package.provenance_notes)


def test_evidence_package_includes_refresh_and_rollback_history(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert len(package.refresh_history) == 1
    assert package.refresh_history[0].run_id == scenario["refresh_run"].run_id
    assert len(package.rollback_history) == 1
    assert package.rollback_history[0].rollback_id == scenario["rollback_record"].rollback_id
    assert package.rollback_history[0].to_version_number == version_1.version_number


def test_evidence_package_revocation_reflects_dataset_version_state(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    lifecycle = LifecycleRepository(session)
    scenario = _fully_wired_scenario(session)
    version_2 = scenario["version_2"]

    lifecycle.revoke_version(version_2.version_id, reason="Defect found in policy application.", revoked_by="security@example.org")

    package = evidence_repo.build_evidence_package(version_2.version_id, generated_by="auditor@example.org")
    assert package.revocation["status"] == "revoked"
    assert package.revocation["revoked_by"] == "security@example.org"
    assert package.revocation["revoked_reason"] == "Defect found in policy application."


def test_evidence_package_audit_trail_includes_registration_refresh_rollback_and_access_events(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    from control_plane.platform.audit import AuditLogRepository

    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    audit = AuditLogRepository(session)
    audit.record(
        event_type=AuditEventType.DATASET_VERSION_ACCESSED,
        actor="qa-engineer@example.org",
        subject=str(version_1.version_id),
        outcome="allowed",
        detail={"purpose": "QA smoke test"},
    )

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    event_types = {e.event_type for e in package.audit_trail}
    assert AuditEventType.DATASET_VERSION_REGISTERED in event_types
    assert AuditEventType.DATASET_VERSION_ACCESSED in event_types
    assert AuditEventType.DATASET_VERSION_ROLLED_BACK in event_types
    # most recent first -- a real ordering check, not a tautology: the
    # extracted timestamps must already be in descending order.
    occurred_ats = [e.occurred_at for e in package.audit_trail]
    assert occurred_ats == sorted(occurred_ats, reverse=True)
    assert len(package.audit_trail) >= 4  # registered x2 subjects-worth, submitted/fulfilled, refresh, rollback, access


def test_generating_a_package_itself_produces_an_audit_event(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    from control_plane.platform.audit import AuditLogRepository

    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    audit = AuditLogRepository(session)
    events = audit.list_events(event_type=AuditEventType.EVIDENCE_PACKAGE_GENERATED, subject=str(version_1.version_id))
    assert len(events) == 1
    assert events[0].actor == "auditor@example.org"
    assert events[0].detail["package_id"] == str(package.package_id)


def test_unknown_version_id_raises_not_found(evidence_repo: EvidenceRepository) -> None:
    with pytest.raises(DatasetVersionNotFoundError):
        evidence_repo.build_evidence_package(uuid4(), generated_by="auditor@example.org")


# ----------------------------------------------------------------------
# Caller-supplied certification report / subset manifest (honest gap)
# ----------------------------------------------------------------------


def test_without_certification_report_integrity_and_quality_reports_are_empty_with_a_note(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.integrity_report == {}
    assert package.quality_report == {}
    assert any("No CertificationReport was supplied" in note for note in package.provenance_notes)


def test_with_certification_report_integrity_and_quality_reports_are_populated(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    from conftest import make_certified_report as _make

    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]
    report = _make(dataset_name="member")

    package = evidence_repo.build_evidence_package(
        version_1.version_id, generated_by="auditor@example.org", certification_report=report
    )

    assert package.certification_report is not None
    assert "referential_integrity" in package.integrity_report
    assert package.integrity_report["referential_integrity"]["passed"] is True
    assert "phi_pii_policy_coverage" in package.quality_report
    assert package.lineage["certification_report_id"] == str(version_1.certification_report_id)


# ----------------------------------------------------------------------
# Bundle checksum (tamper-evidence for the export itself)
# ----------------------------------------------------------------------


def test_bundle_checksum_is_present_and_verifies(session: Session, evidence_repo: EvidenceRepository) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]

    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.bundle_checksum
    assert package.bundle_checksum_algorithm == "sha256"
    assert verify_bundle_checksum(package) is True


def test_bundle_checksum_is_deterministic_for_identical_content(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]
    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    # Recomputing over the exact same content (excluding the checksum
    # field itself, which is what compute_bundle_checksum already
    # excludes) reproduces the identical digest.
    assert compute_bundle_checksum(package) == package.bundle_checksum


def test_tampering_with_a_generated_package_is_detected(
    session: Session, evidence_repo: EvidenceRepository
) -> None:
    scenario = _fully_wired_scenario(session)
    version_1 = scenario["version_1"]
    package = evidence_repo.build_evidence_package(version_1.version_id, generated_by="auditor@example.org")

    assert package.revocation["status"] == "active"  # sanity: not already revoked
    tampered = package.model_copy(update={"revocation": {**package.revocation, "status": "revoked"}})
    assert verify_bundle_checksum(tampered) is False


def test_unsigned_package_fails_verification() -> None:
    from healthcare_tdm_contracts import AuditEvidencePackage, DatasetVersion, DatasetVersionStatus as DVS

    unsigned = AuditEvidencePackage(
        generated_by="auditor@example.org",
        dataset_version_id=uuid4(),
        dataset_name="member",
        version_number=1,
        dataset_manifest=DatasetVersion(
            dataset_name="member",
            version_number=1,
            certification_report_id=uuid4(),
            masking_policy_name="phase3-default",
            masking_policy_version=1,
            masking_engine_version="1.0.0",
            storage_uri="s3://tdm-bucket/member/v1",
            size_bytes=1,
            status=DVS.ACTIVE,
            created_by="pipeline@example.org",
        ),
    )
    assert verify_bundle_checksum(unsigned) is False
