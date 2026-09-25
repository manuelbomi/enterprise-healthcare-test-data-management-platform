"""Health and readiness endpoints.

`/health` was intentionally the only real endpoint in Phase 0 -- every
other route was added in the phase that implements its backing
behavior. `/ready` is Phase 11's fulfillment of the promise this
module's own docstring made back then: "that is the job of /ready,
added once this service has real dependencies to check" -- Phase 7 gave
this service its first real dependency (the lifecycle database), and
this phase finally adds the check. See
`control_plane.platform.readiness`'s module docstring for the
liveness-vs-readiness distinction this split exists to make real.
"""

from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from control_plane.config import Settings, get_settings
from control_plane.db.session import get_engine_for_url
from control_plane.platform.readiness import evaluate_readiness

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str = "control-plane"


class ReadinessCheckResponse(BaseModel):
    name: str
    healthy: bool
    required: bool
    detail: str


class ReadinessResponse(BaseModel):
    status: str
    service: str = "control-plane"
    checks: list[ReadinessCheckResponse]


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check: the process is up and able to respond.

    Deliberately does not check downstream dependencies (database,
    storage) -- a dependency being temporarily unreachable should not
    make an orchestrator kill and restart an otherwise-healthy process.
    See `/ready` for the dependency-aware check.
    """

    return HealthResponse(status="ok")


@router.get("/ready", response_model=ReadinessResponse, responses={503: {"model": ReadinessResponse}})
def ready(settings: Settings = Depends(get_settings)) -> ReadinessResponse:
    """Readiness check: can this process serve real traffic right now.

    Checks the lifecycle database is actually reachable (required --
    a 503 here means "do not route traffic here") and whether the
    Phase 2 catalog artifact is present (informational only -- see
    `control_plane.platform.readiness.check_catalog_artifact`'s
    docstring for why a missing catalog does not fail readiness).
    """

    engine = get_engine_for_url(settings.lifecycle_database_url)
    overall, checks = evaluate_readiness(engine=engine, catalog_path=Path(settings.catalog_path))
    body = ReadinessResponse(
        status="ready" if overall else "not_ready",
        checks=[ReadinessCheckResponse(**vars(c)) for c in checks],
    )
    if not overall:
        raise HTTPException(status_code=503, detail=body.model_dump())
    return body


__all__ = ["ReadinessCheckResponse", "ReadinessResponse", "router"]
