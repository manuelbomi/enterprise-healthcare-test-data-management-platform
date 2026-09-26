"""Certification report read endpoints (Phase 9).

Serves the real `certification_report.json` artifacts Phase 6's
certification pipeline (`services/data-plane/src/data_plane/certification/`)
produces -- same JSON-artifact-handoff pattern as `api/v1/catalog.py`
(ADR-0009). Read-only; certification is not yet submitted as a
control-plane job (`ARCHITECTURE.md`'s Phase 6 note, `docs/problems/problems_phase_06.md`
P6-1).

`GET /certification/reports/{report_id}` is also how Phase 9's Dataset
Detail page (`frontend/src/pages/DatasetDetailPage.tsx`) resolves
certification evidence for a Phase 7 `DatasetVersion`: it looks up
`DatasetVersion.certification_report_id` here.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from control_plane.artifacts import (
    CertificationArtifactNotAvailableError,
    CertificationReportRecord,
    CertificationReportRepository,
)
from control_plane.config import Settings, get_settings

router = APIRouter(prefix="/certification", tags=["certification"])


def get_certification_report_repository(
    settings: Settings = Depends(get_settings),
) -> CertificationReportRepository:
    return CertificationReportRepository(Path(settings.certification_artifacts_root))


@router.get("/reports", response_model=list[CertificationReportRecord])
def list_certification_reports(
    repository: CertificationReportRepository = Depends(get_certification_report_repository),
) -> list[CertificationReportRecord]:
    """Every certification report found under the configured artifact root."""

    try:
        return repository.list_reports()
    except CertificationArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/reports/{report_id}", response_model=CertificationReportRecord)
def get_certification_report(
    report_id: UUID,
    repository: CertificationReportRepository = Depends(get_certification_report_repository),
) -> CertificationReportRecord:
    try:
        record = repository.get_report(report_id)
    except CertificationArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"No certification report with id {report_id}.")
    return record


__all__ = ["get_certification_report_repository", "router"]
