"""FastAPI application entry point for the governance service.

Run locally with:

    uvicorn governance_service.main:app --reload

Phase 12 scope only: a liveness endpoint (`api/health.py`), added so
this service is a real, containerizable, deployable process (Docker,
Docker Compose, Kubernetes/Helm) rather than an unbuildable scaffold,
ahead of the real RBAC/audit-log/secrets-provider/evidence-store
business logic a later phase gives it (see `ARCHITECTURE.md` section
2.4). This mirrors exactly how `control_plane.main` looked in Phase 0,
before Phase 2 added its first real route.
"""

from __future__ import annotations

from fastapi import FastAPI

from governance_service.api import health


def create_app() -> FastAPI:
    """Application factory -- see `control_plane.main.create_app` for the
    identical pattern and rationale (testable construction over a bare
    module-level `app = FastAPI()`)."""

    app = FastAPI(
        title="Enterprise Healthcare Test Data Management Platform — Governance Service",
        version="0.1.0",
        description=(
            "Security/governance plane: RBAC, immutable audit events, "
            "secrets provider adapter, certification evidence. Structural "
            "scaffold as of Phase 12 -- see ARCHITECTURE.md section 2.4."
        ),
    )
    app.include_router(health.router)
    return app


app = create_app()
