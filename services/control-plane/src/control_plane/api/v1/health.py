"""Health and readiness endpoints.

These are intentionally the only real endpoints in Phase 0 — every other
route (snapshot requests, job status, classification review, etc.) is
added in the phase that implements its backing behavior, so the API never
advertises an endpoint that doesn't actually do anything yet.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str = "control-plane"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check: the process is up and able to respond.

    Deliberately does not check downstream dependencies (database,
    storage) — that is the job of /ready, added once this service has
    real dependencies to check (Phase 1 onward).
    """

    return HealthResponse(status="ok")
