"""Subsetting run read endpoints (Phase 9).

Serves the real `subset_manifest.json` artifacts Phase 4's subsetting
engine (`services/data-plane/src/data_plane/subsetting/`) produces --
same JSON-artifact-handoff pattern as `api/v1/catalog.py` (ADR-0009).
Read-only; see `ARCHITECTURE.md`'s Phase 4 note for why subsetting is
still run directly rather than submitted as a control-plane job.
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from control_plane.artifacts import (
    SubsetArtifactNotAvailableError,
    SubsetManifestRecord,
    SubsetManifestRepository,
)
from control_plane.config import Settings, get_settings

router = APIRouter(prefix="/subsetting", tags=["subsetting"])


def get_subset_manifest_repository(settings: Settings = Depends(get_settings)) -> SubsetManifestRepository:
    return SubsetManifestRepository(Path(settings.subsetting_artifacts_root))


@router.get("/manifests", response_model=list[SubsetManifestRecord])
def list_subset_manifests(
    repository: SubsetManifestRepository = Depends(get_subset_manifest_repository),
) -> list[SubsetManifestRecord]:
    """Every subset manifest found under the configured artifact root."""

    try:
        return repository.list_manifests()
    except SubsetArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/manifests/{manifest_id}", response_model=SubsetManifestRecord)
def get_subset_manifest(
    manifest_id: UUID,
    repository: SubsetManifestRepository = Depends(get_subset_manifest_repository),
) -> SubsetManifestRecord:
    try:
        record = repository.get_manifest(manifest_id)
    except SubsetArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"No subset manifest with id {manifest_id}.")
    return record


__all__ = ["get_subset_manifest_repository", "router"]
