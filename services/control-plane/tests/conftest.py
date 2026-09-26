"""Shared fixtures for control-plane tests.

`sample_catalog_path` builds a small, hand-authored catalog fixture using
only `healthcare_tdm_contracts` (never `data_plane` -- see ADR-0003: the
control plane's tests must not depend on the data plane's package). It
covers a deliberate mix of categories/tiers/review states so the catalog
API's filtering can be exercised meaningfully.

`sample_certification_report` (Phase 7) is the same idea applied to a
Phase 6 `CertificationReport`: a small, hand-authored, `CERTIFIED` report
built only from `healthcare_tdm_contracts`, standing in for a real
`data_plane.certification` pipeline run so `services/control-plane`'s
tests never import `data_plane` (ADR-0003). A *real* pipeline run against
a real estate is exercised separately, outside either service's own test
suite -- see `scripts/demo_phase7_lifecycle.py` and
`docs/tutorial/07-dataset-lifecycle-and-refresh.md`.
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from healthcare_tdm_contracts import (
    CatalogEntry,
    CertificationGateResult,
    CertificationGateType,
    CertificationReport,
    CertificationStatus,
    ClassificationMethod,
    ClassificationTier,
    ColumnClassification,
    MaskingPolicy,
    MaskingRule,
    MaskingStrategy,
    RetentionClassification,
    SensitivityCategory,
)

from control_plane.platform.auth import demo_credentials_for_role
from control_plane.platform.rbac import Role

#: Phase 18A (P0-1): every control-plane API test needs a real,
#: verifiable JWT signing key to call `POST /api/v1/auth/login` and any
#: RBAC-gated endpoint. Fixed and test-only -- never resolved from a
#: developer's real shell environment, mirroring
#: `services/data-plane/tests/certification/conftest.py`'s
#: `masking_key`/`signing_key` fixture pattern (a hardcoded, throwaway
#: key, never the same value used anywhere else).
_TEST_JWT_SIGNING_KEY = "control-plane-test-jwt-signing-key-0123456789abcdef"

#: Phase 18A (P1-7): every test that builds an `AuditEvidencePackage`
#: needs a real, verifiable HMAC key to compute/verify its bundle
#: checksum. Fixed and test-only, same convention as
#: `_TEST_JWT_SIGNING_KEY` above.
TEST_EVIDENCE_HMAC_KEY = "control-plane-test-evidence-hmac-key-0123456789abcdef"


@pytest.fixture(autouse=True)
def _jwt_signing_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TDM_CONTROL_PLANE_JWT_SIGNING_KEY", _TEST_JWT_SIGNING_KEY)
    monkeypatch.setenv("TDM_EVIDENCE_HMAC_KEY", TEST_EVIDENCE_HMAC_KEY)


def auth_header(client: TestClient, role: Role) -> dict[str, str]:
    """Log in as the seeded demo identity for `role` (see
    `control_plane.platform.auth.SEEDED_DEMO_USERS`) and return the
    `Authorization` header a test can pass to an RBAC-gated endpoint --
    the real, end-to-end replacement for the pre-Phase-18A pattern of
    setting `"actor_role": role.value` directly in a request body (see
    `problems_final_review.md` P0-1, now resolved)."""

    username, password = demo_credentials_for_role(role)
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def _entry(
    *,
    source_system: str,
    dataset: str,
    column: str,
    category: SensitivityCategory,
    tier: ClassificationTier,
    confidence: float,
    method: ClassificationMethod,
    masking_requirement: MaskingStrategy,
    owner: str,
    retention: RetentionClassification,
    confirmed_by: str | None = None,
) -> CatalogEntry:
    return CatalogEntry(
        classification=ColumnClassification(
            source_system=source_system,
            dataset=dataset,
            column=column,
            tier=tier,
            category=category,
            confidence=confidence,
            detector=f"test:{method.value}",
            method=method,
            reason="Fixture row for control-plane catalog API tests.",
            confirmed_by=confirmed_by,
        ),
        masking_requirement=masking_requirement,
        owner=owner,
        retention_classification=retention,
    )


SAMPLE_ENTRIES: list[CatalogEntry] = [
    _entry(
        source_system="postgres_enrollment",
        dataset="member",
        column="ssn",
        category=SensitivityCategory.DIRECT_IDENTIFIER,
        tier=ClassificationTier.DIRECT_IDENTIFIER,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.EXTENDED,
    ),
    _entry(
        source_system="postgres_enrollment",
        dataset="member",
        column="date_of_birth",
        category=SensitivityCategory.QUASI_IDENTIFIER,
        tier=ClassificationTier.QUASI_IDENTIFIER,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.GENERALIZATION,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.STANDARD,
    ),
    _entry(
        source_system="s3_clinical_data_lake",
        dataset="lab_result",
        column="test_name",
        category=SensitivityCategory.PHI,
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.SYNTHETIC_REPLACEMENT,
        owner="Clinical Data Engineering",
        retention=RetentionClassification.EXTENDED,
    ),
    _entry(
        source_system="postgres_enrollment",
        dataset="provider",
        column="npi",
        category=SensitivityCategory.PII,
        tier=ClassificationTier.QUASI_IDENTIFIER,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.GENERALIZATION,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.STANDARD,
    ),
    _entry(
        source_system="object_storage_claims_parquet",
        dataset="claim",
        column="adjustment_reason_code",
        category=SensitivityCategory.SENSITIVE,
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        confidence=0.3,
        method=ClassificationMethod.RULE_BASED,
        masking_requirement=MaskingStrategy.SYNTHETIC_REPLACEMENT,
        owner="Claims Data Engineering",
        retention=RetentionClassification.STANDARD,
    ),  # low confidence, unconfirmed -> needs_review True
    _entry(
        source_system="postgres_enrollment",
        dataset="plan",
        column="plan_name",
        category=SensitivityCategory.NON_SENSITIVE,
        tier=ClassificationTier.NON_SENSITIVE,
        confidence=1.0,
        method=ClassificationMethod.SCHEMA_BASED,
        masking_requirement=MaskingStrategy.PASSTHROUGH,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.PERSISTENT_REFERENCE,
    ),
    _entry(
        source_system="postgres_enrollment",
        dataset="provider",
        column="specialty",
        category=SensitivityCategory.SENSITIVE,
        tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
        confidence=1.0,
        method=ClassificationMethod.MANUAL_OVERRIDE,
        masking_requirement=MaskingStrategy.SYNTHETIC_REPLACEMENT,
        owner="Enrollment Data Engineering",
        retention=RetentionClassification.STANDARD,
        confirmed_by="data-governance-steward@example.org",
    ),
]


@pytest.fixture
def sample_catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.json"
    payload = [json.loads(entry.model_dump_json()) for entry in SAMPLE_ENTRIES]
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    return path


def make_certified_report(
    *, dataset_name: str = "tiny-fixed_population", status: CertificationStatus = CertificationStatus.CERTIFIED
) -> CertificationReport:
    """A hand-authored, structurally realistic `CertificationReport` --
    same shape a real `data_plane.certification.pipeline.run_certification_pipeline`
    run produces (see `docs/tutorial/06-certification-pipeline.md`'s real
    sample output), built without importing `data_plane` (ADR-0003)."""

    return CertificationReport(
        report_id=uuid4(),
        dataset_name=dataset_name,
        scale_profile="tiny",
        status=status,
        masking_policy_name="phase3-default",
        masking_policy_version=1,
        masking_engine_version="1.0.0",
        gates=[
            CertificationGateResult(gate=CertificationGateType.PHI_PII_POLICY_COVERAGE, passed=True, detail="ok"),
            CertificationGateResult(gate=CertificationGateType.MASKING_COMPLETION, passed=True, detail="ok"),
            CertificationGateResult(gate=CertificationGateType.REFERENTIAL_INTEGRITY, passed=True, detail="ok"),
        ],
        row_count_reconciliation={"member": "source=26 selected=10 final=10"},
        integrity_signature="deadbeef",
    )


@pytest.fixture
def sample_certification_report() -> CertificationReport:
    return make_certified_report()


def make_sample_masking_policy(*, version: int = 1) -> MaskingPolicy:
    """A small, hand-authored, structurally realistic `MaskingPolicy` --
    same shape (`name="phase3-default"`) the real Phase 3
    `data_plane.masking.policy.DEFAULT_POLICY` uses, built without
    importing `data_plane` (ADR-0003: control-plane tests never depend
    on the data-plane package). Used by
    `test_governance_repository.py`/`test_governance_api.py` (Phase 10)
    to draft/approve a governed `MaskingPolicyVersion`. `version` matches
    `make_certified_report`'s `masking_policy_version=1` default, so a
    test can construct a narrative where a certification report and a
    governed policy version agree on which policy produced the data."""

    return MaskingPolicy(
        name="phase3-default",
        version=version,
        rules=[
            MaskingRule(
                tier=ClassificationTier.DIRECT_IDENTIFIER,
                strategy=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
                scope="member-id-global",
                field_pattern=r"^member_id$",
                preserve_linkage=True,
            ),
            MaskingRule(
                tier=ClassificationTier.DIRECT_IDENTIFIER,
                strategy=MaskingStrategy.DETERMINISTIC_TOKENIZATION,
                scope="direct-identifier-default",
            ),
            MaskingRule(
                tier=ClassificationTier.QUASI_IDENTIFIER,
                strategy=MaskingStrategy.GENERALIZATION,
                scope="quasi-identifier-default",
            ),
            MaskingRule(
                tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE,
                strategy=MaskingStrategy.SYNTHETIC_REPLACEMENT,
                scope="sensitive-clinical-default",
            ),
            MaskingRule(
                tier=ClassificationTier.NON_SENSITIVE,
                strategy=MaskingStrategy.PASSTHROUGH,
                scope="non-sensitive-default",
            ),
        ],
    )
