"""FastAPI application entry point for the control plane.

Run locally with:

    uvicorn control_plane.main:app --reload

Phase 0 scope: only a health/readiness endpoint is wired up, so the
service's shape (app factory, router registration pattern) is fixed
before real routes are added in Phase 2 onward. See api/v1/ for versioned
route modules.
"""

from __future__ import annotations

from fastapi import FastAPI

from control_plane.api.v1 import health
from control_plane.config import get_settings


def create_app() -> FastAPI:
    """Application factory.

    Using a factory (rather than a bare module-level `app = FastAPI()`
    with routes attached ad hoc) keeps app construction testable — tests
    can call create_app() with overridden settings/dependencies instead of
    importing a single shared instance.
    """

    settings = get_settings()
    app = FastAPI(
        title="Enterprise Healthcare Test Data Management Platform — Control Plane",
        version="0.1.0",
        description=(
            "Orchestration, policy, and the public API for requesting "
            "synthetic/masked/subsetted test data snapshots. See "
            "ARCHITECTURE.md at the repository root."
        ),
    )
    app.include_router(health.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
