# tdm-control-plane

The control plane service: orchestration, policy resolution, capacity
checks, and the platform's public REST API. See `ARCHITECTURE.md` section
2.1 at the repository root for its full responsibilities and boundaries.

This service also owns the metadata plane's PostgreSQL schema (models
under `src/control_plane/db/`) — the metadata plane is a data store, not a
separate deployable service, and the control plane is its primary writer/
reader on behalf of the rest of the system.

## Phase 7 status

This service now has two real capability sets:

- `api/v1/catalog.py` (Phase 2) -- read-only PHI/PII catalog, served
  from a JSON artifact another plane produces (ADR-0009).
- `api/v1/lifecycle.py` (Phase 7) -- dataset lifecycle and refresh
  management, the first real, database-backed domain model this
  service owns: dataset versions, refresh policies, environment
  dataset requests, on-demand/scheduled refresh, rollback, and
  revocation, backed by `db/models.py` (SQLite locally, Postgres-
  portable) and `domain/lifecycle/`. See
  `docs/tutorial/07-dataset-lifecycle-and-refresh.md` and
  `docs/adr/0012-refresh-orchestration-abstraction.md`.

Everything else in `ARCHITECTURE.md` section 2.1 the control plane is
scoped to own (job orchestration/DAG construction, capacity/quota
checks, RBAC enforcement) remains not yet implemented -- see
`problems_master.md` and `problems_phase_07.md` for what's next.

## Layout

```
src/control_plane/
├── main.py             # FastAPI app entry point
├── config.py            # Settings (env-var driven), see pydantic-settings
├── api/v1/
│   ├── catalog.py         # Phase 2: read-only PHI/PII catalog (JSON artifact handoff)
│   └── lifecycle.py       # Phase 7: dataset lifecycle and refresh management (real DB)
├── domain/
│   └── lifecycle/          # Phase 7: cadence math, state machine, scheduler, repository
├── db/
│   ├── models.py           # Phase 7: SQLAlchemy models (SQLite/Postgres-portable)
│   └── session.py          # Phase 7: engine/session management
└── catalog/                # Phase 2: JSON-artifact catalog repository
```

## Local development

```bash
pip install -e ".[dev]"
uvicorn control_plane.main:app --reload
```

Try the dataset lifecycle API end to end against real data (runs the
real Phase 6 certification pipeline twice, then registers/requests/
refreshes/rolls back/revokes through the real API):

```bash
python scripts/demo_phase7_lifecycle.py   # from the repository root
```
