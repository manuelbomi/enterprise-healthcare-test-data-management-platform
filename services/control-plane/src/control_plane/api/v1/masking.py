"""Masking run read endpoints (Phase 9).

Serves the real `masking_run_summary.json` artifacts Phase 3's masking
engine (`services/data-plane/src/data_plane/masking/`) produces, via the
JSON artifact handoff pattern ADR-0009 established for the catalog.
Read-only: the control plane does not run masking itself -- masking is a
data-plane concern (`ARCHITECTURE.md` section 2.2) not yet wired to a
control-plane-submitted job (see `docs/problems/problems_phase_03.md` P3-3 and
`ARCHITECTURE.md`'s Phase 3 note).

Every route can raise HTTP 503 (not 500) if the configured artifact root
doesn't exist yet -- an expected, recoverable condition, not a service
failure -- mirroring `api/v1/catalog.py`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException

from control_plane.artifacts import MaskingArtifactNotAvailableError, MaskingRunRecord, MaskingRunRepository
from control_plane.config import Settings, get_settings

router = APIRouter(prefix="/masking", tags=["masking"])


def get_masking_run_repository(settings: Settings = Depends(get_settings)) -> MaskingRunRepository:
    return MaskingRunRepository(Path(settings.masking_artifacts_root))


@router.get("/runs", response_model=list[MaskingRunRecord])
def list_masking_runs(
    repository: MaskingRunRepository = Depends(get_masking_run_repository),
) -> list[MaskingRunRecord]:
    """Every masking run summary found under the configured artifact root."""

    try:
        return repository.list_runs()
    except MaskingArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


__all__ = ["get_masking_run_repository", "router"]
