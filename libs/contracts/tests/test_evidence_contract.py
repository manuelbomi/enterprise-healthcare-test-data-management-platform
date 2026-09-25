"""Smoke tests for `healthcare_tdm_contracts.evidence.AuditEvidencePackage`
(Phase 13). Mirrors `test_contracts_smoke.py`'s convention: these
contracts have no behavior beyond validation/serialization, so the
tests here confirm round-tripping and defaults, not aggregation logic
(that belongs to `control_plane.domain.evidence`, tested in
`services/control-plane/tests/test_evidence_repository.py`).
"""

from __future__ import annotations

from uuid import uuid4

from healthcare_tdm_contracts import (
    COMPLIANCE_DISCLAIMER,
    AuditEvidencePackage,
    DatasetVersion,
    DatasetVersionStatus,
)


def _sample_dataset_version() -> DatasetVersion:
    return DatasetVersion(
        dataset_name="member",
        version_number=1,
        certification_report_id=uuid4(),
        masking_policy_name="phase3-default",
        masking_policy_version=1,
        masking_engine_version="1.0.0",
        storage_uri="s3://tdm-bucket/member/v1",
        size_bytes=1_000,
        status=DatasetVersionStatus.ACTIVE,
        created_by="pipeline@example.org",
    )


def test_audit_evidence_package_round_trips() -> None:
    version = _sample_dataset_version()
    package = AuditEvidencePackage(
        generated_by="auditor@example.org",
        dataset_version_id=version.version_id,
        dataset_name=version.dataset_name,
        version_number=version.version_number,
        dataset_manifest=version,
        bundle_checksum="deadbeef",
    )
    assert AuditEvidencePackage.model_validate_json(package.model_dump_json()) == package


def test_audit_evidence_package_defaults_are_empty_not_none() -> None:
    version = _sample_dataset_version()
    package = AuditEvidencePackage(
        generated_by="auditor@example.org",
        dataset_version_id=version.version_id,
        dataset_name=version.dataset_name,
        version_number=version.version_number,
        dataset_manifest=version,
    )
    assert package.environment_requests == []
    assert package.consumer_requests == []
    assert package.classification_summary == {}
    assert package.masking_policy_version is None
    assert package.certification_report is None
    assert package.subset_manifest is None
    assert package.integrity_report == {}
    assert package.quality_report == {}
    assert package.refresh_history == []
    assert package.rollback_history == []
    assert package.revocation == {}
    assert package.audit_trail == []
    assert package.lineage == {}
    assert package.bundle_checksum == ""
    assert package.bundle_checksum_algorithm == "sha256"
    assert package.provenance_notes == []


def test_audit_evidence_package_never_claims_hipaa_compliance() -> None:
    # The one claim this package's disclaimer is NOT allowed to make.
    assert "guarantee" in COMPLIANCE_DISCLAIMER.lower()
    assert "not itself a certification" in COMPLIANCE_DISCLAIMER.lower()
    assert "hipaa" in COMPLIANCE_DISCLAIMER.lower()

    version = _sample_dataset_version()
    package = AuditEvidencePackage(
        generated_by="auditor@example.org",
        dataset_version_id=version.version_id,
        dataset_name=version.dataset_name,
        version_number=version.version_number,
        dataset_manifest=version,
    )
    assert package.compliance_disclaimer == COMPLIANCE_DISCLAIMER
