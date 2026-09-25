# tdm-control-plane

The control plane service: orchestration, policy resolution, capacity
checks, and the platform's public REST API. See `ARCHITECTURE.md` section
2.1 at the repository root for its full responsibilities and boundaries.

This service also owns the metadata plane's PostgreSQL schema (models
under `src/control_plane/db/`) — the metadata plane is a data store, not a
separate deployable service, and the control plane is its primary writer/
reader on behalf of the rest of the system.

## Phase 0 status

This package is a structural scaffold: package layout, FastAPI app entry
point, and module placeholders exist so the shape of the service is fixed.
No routes do real work yet, no database migrations exist yet, and no
dependencies have been installed or verified. See `problems_master.md` at
the repository root (`P0-1`) and `ROADMAP.md` (Phases 1-2) for what's next.

## Layout

```
src/control_plane/
├── main.py          # FastAPI app entry point
├── config.py         # Settings (env-var driven), see pydantic-settings
├── api/v1/            # Versioned API routers
├── domain/            # Orchestration and policy logic (no I/O)
└── db/                 # SQLAlchemy models + session management (metadata plane schema)
```

## Local development (once Phase 1/2 land)

```bash
pip install -e ".[dev]"
uvicorn control_plane.main:app --reload
```
