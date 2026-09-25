"""Data catalog read endpoints.

Serves the PHI/PII classification catalog the data-plane discovery engine
produces (`services/data-plane/src/data_plane/discovery/`), via the JSON
artifact handoff documented in ADR-0009
(`docs/adr/0009-catalog-artifact-handoff.md`). Read-only: the control
plane does not classify anything itself -- classification is a data-plane
concern (`ARCHITECTURE.md` section 2.2) -- it surfaces what discovery
already produced, with the filtering/aggregation a data steward or
auditor needs.

Every route can raise HTTP 503 (not 500) if the catalog artifact hasn't
been generated yet for this environment -- an expected, recoverable
condition, not a service failure. See `CatalogNotAvailableError`.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from healthcare_tdm_contracts import CatalogEntry, ClassificationTier, SensitivityCategory

from control_plane.catalog import CatalogNotAvailableError, CatalogRepository
from control_plane.config import Settings, get_settings

router = APIRouter(prefix="/catalog", tags=["catalog"])


def get_catalog_repository(settings: Settings = Depends(get_settings)) -> CatalogRepository:
    """FastAPI dependency: build a repository pointed at the configured
    catalog artifact path. A new `CatalogRepository` per request is cheap
    (it lazy-loads and caches on first read within the request); tests
    override this dependency directly to point at a fixture file."""

    return CatalogRepository(Path(settings.catalog_path))


@router.get("", response_model=list[CatalogEntry])
def list_catalog_entries(
    source_system: str | None = None,
    dataset: str | None = None,
    category: SensitivityCategory | None = None,
    tier: ClassificationTier | None = None,
    needs_review: bool | None = None,
    repository: CatalogRepository = Depends(get_catalog_repository),
) -> list[CatalogEntry]:
    """List catalog entries (classified columns), optionally filtered by
    source system, dataset, category, tier, and/or review status."""

    try:
        return repository.list_entries(
            source_system=source_system,
            dataset=dataset,
            category=category,
            tier=tier,
            needs_review=needs_review,
        )
    except CatalogNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/summary")
def catalog_summary(repository: CatalogRepository = Depends(get_catalog_repository)) -> dict[str, object]:
    """Catalog-wide counts: total columns/datasets, a breakdown by
    category, and how many entries still need data-steward review."""

    try:
        return repository.summary()
    except CatalogNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/datasets")
def list_datasets(repository: CatalogRepository = Depends(get_catalog_repository)) -> list[dict[str, object]]:
    """One row per known (source_system, dataset): column count, most
    severe category present, and owner -- a dataset-level overview."""

    try:
        return repository.list_datasets()
    except CatalogNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/{source_system}/{dataset}/{column}", response_model=CatalogEntry)
def get_catalog_entry(
    source_system: str,
    dataset: str,
    column: str,
    repository: CatalogRepository = Depends(get_catalog_repository),
) -> CatalogEntry:
    """The classification of a single (source_system, dataset, column)."""

    try:
        entry = repository.get_entry(source_system, dataset, column)
    except CatalogNotAvailableError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if entry is None:
        raise HTTPException(
            status_code=404,
            detail=f"No catalog entry for {source_system}/{dataset}/{column}.",
        )
    return entry
