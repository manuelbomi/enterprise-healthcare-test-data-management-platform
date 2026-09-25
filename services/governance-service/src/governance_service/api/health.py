"""Liveness endpoint for the governance service.

Mirrors the exact pattern `control_plane.api.v1.health` established in
Phase 0: `/health` only proves the process is up and able to respond --
it deliberately does not check any downstream dependency. Unlike the
control plane, this service has no database or other real dependency
yet (see `ARCHITECTURE.md` section 2.4 and
`docs/adr/0014-masking-governance-lives-in-control-plane.md` for why
RBAC/audit/secrets/evidence-store business logic still lives elsewhere
as of Phase 12), so there is no `/ready` endpoint here yet either --
adding one before there is a real dependency to check would be a fake
signal, not a real readiness gate. This module exists in Phase 12
specifically so this service has *something* real to containerize,
deploy, and health-check end to end (Docker, Docker Compose, Helm),
proving the deployment pipeline works for every service directory now,
rather than only for control-plane and frontend.
"""

from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(tags=["health"])


class HealthResponse(BaseModel):
    status: str
    service: str = "governance-service"


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    """Liveness check: the process is up and able to respond."""

    return HealthResponse(status="ok")


__all__ = ["HealthResponse", "router"]
