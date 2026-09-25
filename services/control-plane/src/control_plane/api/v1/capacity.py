"""Storage and compute capacity-planning endpoints (Phase 8).

Reuses `api/v1/lifecycle.py`'s `get_db_session`/`get_lifecycle_repository`
dependencies rather than redefining them, so a test overriding
`get_db_session` (see `test_lifecycle_api.py`'s pattern) transparently
also points this router at the same temporary database -- both routers
share the exact same session-per-request wiring, per
`control_plane.db.session`.

Route handlers do exactly three things, the same convention
`api/v1/lifecycle.py` establishes: resolve a `CapacityPlanner` via
dependency injection, call one of its methods (or the pure
`illustrative_capacity_plan` function), and translate domain exceptions
to HTTP status codes. No business logic lives here -- see
`control_plane.domain.capacity` for that.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from healthcare_tdm_contracts import (
    CapacityPlan,
    DatasetVersionFootprint,
    EnvironmentCapacityDemand,
    IllustrativeCapacityPlan,
    IllustrativeCapacityScenario,
    VacuumCandidate,
)
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.domain.capacity import CapacityPlanner, illustrative_capacity_plan
from control_plane.domain.lifecycle import (
    DatasetVersionNotFoundError,
    EnvironmentRequestNotFoundError,
    LifecycleRepository,
)

router = APIRouter(prefix="/capacity", tags=["capacity"])


def get_capacity_planner(session: Session = Depends(get_db_session)) -> CapacityPlanner:
    return CapacityPlanner(LifecycleRepository(session))


@router.get("/dataset-versions/{version_id}/footprint", response_model=DatasetVersionFootprint)
def get_dataset_version_footprint(
    version_id: UUID, planner: CapacityPlanner = Depends(get_capacity_planner)
) -> DatasetVersionFootprint:
    """Real storage/compute footprint of one registered `DatasetVersion`
    -- see `CapacityPlanner.dataset_version_footprint`."""

    try:
        return planner.dataset_version_footprint(version_id)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/environment-requests/{request_id}/demand", response_model=EnvironmentCapacityDemand)
def get_environment_capacity_demand(
    request_id: UUID, planner: CapacityPlanner = Depends(get_capacity_planner)
) -> EnvironmentCapacityDemand:
    """Real storage/compute demand one `EnvironmentDatasetRequest`
    places on the platform -- see `CapacityPlanner.environment_capacity_demand`."""

    try:
        return planner.environment_capacity_demand(request_id)
    except EnvironmentRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/plan", response_model=CapacityPlan)
def get_capacity_plan(
    dataset_name: str | None = None, planner: CapacityPlanner = Depends(get_capacity_planner)
) -> CapacityPlan:
    """The real, DB-backed aggregate capacity report: naive (every
    environment its own independent physical copy) vs. shared (Phase 7's
    real architecture -- one physical artifact per distinct dataset
    version) storage totals, plus every dataset version's footprint and
    every environment's demand. See `CapacityPlanner.capacity_plan`."""

    return planner.capacity_plan(dataset_name=dataset_name)


@router.get("/vacuum-candidates", response_model=list[VacuumCandidate])
def get_vacuum_candidates(
    dataset_name: str | None = None, planner: CapacityPlanner = Depends(get_capacity_planner)
) -> list[VacuumCandidate]:
    """Dataset versions that are safe to physically delete: terminal
    status (expired/revoked/rolled_back) and referenced by zero
    environment requests. Read-only -- see `problems_phase_08.md` P8-3
    for why this identifies candidates rather than deleting anything."""

    return planner.vacuum_candidates(dataset_name=dataset_name)


@router.get("/illustrative-plan", response_model=IllustrativeCapacityPlan)
def get_default_illustrative_plan(
    production_baseline_tb: float = Query(
        default=100.0, gt=0, description="Hypothetical production size in decimal TB (10^12 bytes)."
    ),
) -> IllustrativeCapacityPlan:
    """`ROADMAP.md` Phase 8's worked example with zero setup: a
    hypothetical production baseline (default 100 TB, matching the
    example) sized against
    `healthcare_tdm_contracts.DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS`
    (DEV/QA 10%, SIT 5%, UAT 15%, PERFORMANCE 100%). Pure calculation --
    no database access. For a custom scenario, use
    `POST /illustrative-plan` instead."""

    from healthcare_tdm_contracts import TERABYTE_BYTES

    scenario = IllustrativeCapacityScenario(
        production_baseline_bytes=int(production_baseline_tb * TERABYTE_BYTES)
    )
    return illustrative_capacity_plan(scenario)


@router.post("/illustrative-plan", response_model=IllustrativeCapacityPlan)
def post_illustrative_plan(scenario: IllustrativeCapacityScenario) -> IllustrativeCapacityPlan:
    """The same calculation as `GET /illustrative-plan`, against a
    caller-supplied `IllustrativeCapacityScenario` (a custom production
    baseline and/or a custom set of per-environment requirements/share
    tiers). Pure calculation -- no database access; see
    `problems_phase_08.md` P8-4 for why scenarios are not persisted."""

    return illustrative_capacity_plan(scenario)


__all__ = ["get_capacity_planner", "router"]
