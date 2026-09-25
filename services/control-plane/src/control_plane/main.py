"""FastAPI application entry point for the control plane.

Run locally with:

    uvicorn control_plane.main:app --reload

Phase 0 scope: only a health/readiness endpoint was wired up. Phase 2
adds the first real business-capability route set (`api/v1/catalog.py`,
the PHI/PII data catalog). Phase 7 adds the first database-backed one
(`api/v1/lifecycle.py`, dataset lifecycle and refresh management).
Phase 8 adds capacity-planning endpoints built on top of it
(`api/v1/capacity.py`). See api/v1/ for versioned route modules.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from control_plane.api.v1 import capacity, catalog, certification, health, lifecycle, masking, subsetting, synthetic
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
    # Phase 9: only installed when TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS
    # is set -- the documented default (same-origin, via the Vite dev
    # server proxy) needs no CORS at all. See `config.py`.
    if settings.cors_allowed_origins_list:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.cors_allowed_origins_list,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["*"],
        )
    app.include_router(health.router, prefix=settings.api_v1_prefix)
    app.include_router(catalog.router, prefix=settings.api_v1_prefix)
    app.include_router(lifecycle.router, prefix=settings.api_v1_prefix)
    app.include_router(capacity.router, prefix=settings.api_v1_prefix)
    app.include_router(masking.router, prefix=settings.api_v1_prefix)
    app.include_router(subsetting.router, prefix=settings.api_v1_prefix)
    app.include_router(synthetic.router, prefix=settings.api_v1_prefix)
    app.include_router(certification.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
