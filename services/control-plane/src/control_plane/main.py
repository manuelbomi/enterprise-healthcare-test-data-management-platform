"""FastAPI application entry point for the control plane.

Run locally with:

    uvicorn control_plane.main:app --reload

Phase 0 scope: only a health/readiness endpoint was wired up. Phase 2
adds the first real business-capability route set (`api/v1/catalog.py`,
the PHI/PII data catalog). Phase 7 adds the first database-backed one
(`api/v1/lifecycle.py`, dataset lifecycle and refresh management).
Phase 8 adds capacity-planning endpoints built on top of it
(`api/v1/capacity.py`). Phase 10 adds centralized masking governance
endpoints (`api/v1/governance.py`), which call directly into the same
Phase 7 lifecycle schema/session. See api/v1/ for versioned route
modules.
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI, Request

from fastapi.middleware.cors import CORSMiddleware

from control_plane.api.v1 import (
    audit,
    auth,
    capacity,
    catalog,
    certification,
    evidence,
    governance,
    health,
    lifecycle,
    masking,
    subsetting,
    synthetic,
)
from control_plane.config import get_settings
from control_plane.platform.logging_config import (
    configure_logging,
    new_correlation_id,
    set_correlation_id,
)

_request_logger = logging.getLogger("control_plane.request")


def create_app() -> FastAPI:
    """Application factory.

    Using a factory (rather than a bare module-level `app = FastAPI()`
    with routes attached ad hoc) keeps app construction testable — tests
    can call create_app() with overridden settings/dependencies instead of
    importing a single shared instance.
    """

    settings = get_settings()
    # Phase 18A (resolves `problems_final_review.md` P1-5): the first
    # real consumer of `settings.log_level` -- see
    # `control_plane.platform.logging_config`'s module docstring for
    # exactly what this does (real structured JSON logs, correlation-ID
    # tagged) and does not (no real metrics/tracing infrastructure).
    configure_logging(settings.log_level)
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

    @app.middleware("http")
    async def log_requests(request: Request, call_next):  # type: ignore[no-untyped-def]
        """Phase 18A (P1-5): one structured JSON log line per request --
        the real, minimal request/job-event emission
        `ARCHITECTURE.md` section 3.3 claimed and this repository never
        actually built before this phase. A correlation ID is read from
        an incoming `X-Correlation-Id` header if present (so a caller
        can thread its own trace ID through), otherwise generated fresh
        per request, and echoed back on the response header so a client
        can correlate its own logs with this service's."""

        correlation_id = request.headers.get("x-correlation-id") or new_correlation_id()
        set_correlation_id(correlation_id)
        started_at = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - started_at) * 1000
        _request_logger.info(
            "request completed",
            extra={
                "correlation_id": correlation_id,
                "http_method": request.method,
                "http_path": request.url.path,
                "http_status_code": response.status_code,
                "duration_ms": round(duration_ms, 2),
            },
        )
        response.headers["X-Correlation-Id"] = correlation_id
        return response

    app.include_router(health.router, prefix=settings.api_v1_prefix)
    app.include_router(auth.router, prefix=settings.api_v1_prefix)
    app.include_router(catalog.router, prefix=settings.api_v1_prefix)
    app.include_router(lifecycle.router, prefix=settings.api_v1_prefix)
    app.include_router(capacity.router, prefix=settings.api_v1_prefix)
    app.include_router(masking.router, prefix=settings.api_v1_prefix)
    app.include_router(subsetting.router, prefix=settings.api_v1_prefix)
    app.include_router(synthetic.router, prefix=settings.api_v1_prefix)
    app.include_router(certification.router, prefix=settings.api_v1_prefix)
    app.include_router(governance.router, prefix=settings.api_v1_prefix)
    app.include_router(audit.router, prefix=settings.api_v1_prefix)
    app.include_router(evidence.router, prefix=settings.api_v1_prefix)
    return app


app = create_app()
