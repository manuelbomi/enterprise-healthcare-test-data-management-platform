"""Audit Evidence Package endpoint (Phase 13).

One route: generating an `AuditEvidencePackage` for a dataset version is
a computation/aggregation action (it appends a real
`EVIDENCE_PACKAGE_GENERATED` audit event as a side effect -- see
`control_plane.domain.evidence.EvidenceRepository`), not a plain read,
so it is a `POST`, mirroring how `api/v1/lifecycle.py`'s `refresh`/
`rollback` actions are also `POST`s despite not creating a brand-new
top-level resource in the REST-purist sense.

Reuses `api/v1/lifecycle.py`'s `get_db_session` dependency, the same
convention `api/v1/governance.py`/`api/v1/audit.py` already establish,
so this router shares one transaction/schema with every other Phase 7/
10/11 router in this service.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from healthcare_tdm_contracts import AuditEvidencePackage, CertificationReport, SubsetManifest
from pydantic import BaseModel
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.catalog import CatalogRepository
from control_plane.config import Settings, get_settings
from control_plane.domain.evidence import EvidenceRepository
from control_plane.domain.lifecycle import DatasetVersionNotFoundError

router = APIRouter(prefix="/evidence", tags=["evidence"])


def get_evidence_repository(
    session: Session = Depends(get_db_session), settings: Settings = Depends(get_settings)
) -> EvidenceRepository:
    return EvidenceRepository(session, catalog_repository=CatalogRepository(Path(settings.catalog_path)))


class GenerateEvidencePackageRequest(BaseModel):
    generated_by: str
    #: The real Phase 6 CertificationReport for this dataset version, if
    #: the caller has it -- `services/control-plane` does not durably
    #: store this itself (see `docs/problems/problems_phase_13.md` P13-1). Embedded
    #: verbatim (never re-derived or re-verified) if supplied.
    certification_report: CertificationReport | None = None
    #: The real Phase 4 SubsetManifest, same caveat.
    subset_manifest: SubsetManifest | None = None


@router.post("/dataset-versions/{version_id}/package", response_model=AuditEvidencePackage, status_code=201)
def generate_evidence_package(
    version_id: UUID,
    body: GenerateEvidencePackageRequest,
    repository: EvidenceRepository = Depends(get_evidence_repository),
) -> AuditEvidencePackage:
    """Aggregate every real artifact this control plane holds about
    `version_id` (dataset manifest, classification summary, masking
    policy version + approvals, provisioning/refresh/rollback/
    revocation history, audit trail) into one checksum-verified
    `AuditEvidencePackage`. See `docs/COMPLIANCE_EVIDENCE.md` for what
    this package does and does not claim."""

    try:
        return repository.build_evidence_package(
            version_id,
            generated_by=body.generated_by,
            certification_report=body.certification_report,
            subset_manifest=body.subset_manifest,
        )
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


__all__ = ["get_evidence_repository", "router"]
