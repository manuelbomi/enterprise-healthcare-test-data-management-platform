"""API layer: versioned FastAPI routers.

Routes here should stay thin — request/response marshalling and calling
into `control_plane.domain` for actual orchestration/policy logic. Routes
must never contain business logic themselves (see domain/ for where that
belongs) and must never perform data-plane work directly.
"""
