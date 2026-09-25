# Problems — Phase 1 (Synthetic Multi-System Healthcare Data Estate)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process.
Written before implementation began, updated as work proceeded. Resolved
entries are removed (not marked resolved) once fixed and tested; anything
left below at the end of the phase is a genuine open issue for a later
phase to pick up.

## Anticipated risk, carried forward as an open item

### P1-1 — Reference data estate has not been exercised against a real PostgreSQL server

- **Status:** open (deliberately out of scope for this phase)
- **Description:** `postgres_models.py` / `writers/postgres_writer.py`
  default to a local SQLite file (zero-infrastructure path) and accept a
  real PostgreSQL DSN via `--database-url`, but no real PostgreSQL server
  was available in this environment to test against (Docker Compose
  infra lands in Phase 4). The models deliberately avoid Postgres-only
  column types specifically so the same code path is expected to work
  unmodified, but this has not been verified against an actual Postgres
  instance.
- **Repro / detail:** Once `infra/docker/docker-compose.yml`'s Postgres
  service is available (Phase 4), run:
  `python -m data_plane.reference_data.cli --scale tiny --database-url postgresql+psycopg://tdm:tdm@localhost:5432/tdm_source_enrollment`
  and confirm it succeeds identically to the SQLite path.
- **Affected files:** `services/data-plane/src/data_plane/reference_data/postgres_models.py`,
  `services/data-plane/src/data_plane/reference_data/writers/postgres_writer.py`
- **Owner for resolution:** Phase 4 (local infrastructure) or whichever
  phase first stands up a real Postgres-backed integration test.

