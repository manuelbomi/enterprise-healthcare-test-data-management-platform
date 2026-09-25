"""Synthetic scenario generation run read endpoints (Phase 9).

Serves the real `synthetic_generation_manifest.json` artifacts Phase 5's
synthetic scenario generator
(`services/data-plane/src/data_plane/synthetic/`) produces -- same
JSON-artifact-handoff pattern as `api/v1/catalog.py` (ADR-0009).
Read-only; synthetic generation is not yet submitted as a control-plane
job (`ARCHITECTURE.md`'s Phase 5 note is silent on this because Phase 5
predates that convention being written down explicitly, but the same gap
applies -- see `problems_phase_09.md`).
"""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException

from control_plane.artifacts import (
    SyntheticArtifactNotAvailableError,
    SyntheticManifestRecord,
    SyntheticManifestRepository,
)
from control_plane.config import Settings, get_settings

router = APIRouter(prefix="/synthetic", tags=["synthetic"])


def get_synthetic_manifest_repository(settings: Settings = Depends(get_settings)) -> SyntheticManifestRepository:
    return SyntheticManifestRepository(Path(settings.synthetic_artifacts_root))


@router.get("/manifests", response_model=list[SyntheticManifestRecord])
def list_synthetic_manifests(
    repository: SyntheticManifestRepository = Depends(get_synthetic_manifest_repository),
) -> list[SyntheticManifestRecord]:
    """Every synthetic scenario generation manifest found under the
    configured artifact root."""

    try:
        return repository.list_manifests()
    except SyntheticArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/manifests/{manifest_id}", response_model=SyntheticManifestRecord)
def get_synthetic_manifest(
    manifest_id: UUID,
    repository: SyntheticManifestRepository = Depends(get_synthetic_manifest_repository),
) -> SyntheticManifestRecord:
    try:
        record = repository.get_manifest(manifest_id)
    except SyntheticArtifactNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"No synthetic generation manifest with id {manifest_id}.")
    return record


__all__ = ["get_synthetic_manifest_repository", "router"]
