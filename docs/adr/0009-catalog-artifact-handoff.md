# ADR-0009: Hand the PHI/PII data catalog between planes as a JSON artifact (interim)

## Status

Accepted (interim — superseded once the metadata plane's real PostgreSQL
catalog table exists; see "Consequences")

## Context

Phase 2 needs the control plane's public REST API to serve the PHI/PII
data catalog (`CatalogEntry` rows: classification + masking requirement +
owner + retention classification) that the data plane's discovery engine
(`services/data-plane/src/data_plane/discovery/`) produces.

Two constraints collide:

1. **ADR-0003 (plane separation)** is explicit: a plane may only be
   reached through its published interface, never by one plane importing
   another plane's internal implementation code. The control plane
   (`tdm-control-plane`) and data plane (`tdm-data-plane`) are separate
   installable packages with no dependency edge between them (ADR-0002),
   and the control plane must not depend on `pyspark`/`pandas`/`pyarrow`
   just to read a catalog.
2. **ADR-0004 (PostgreSQL metadata store)** says the metadata plane —
   where `DATA_GOVERNANCE.md` B.1 says the classification store belongs —
   is a real PostgreSQL schema owned by the control plane, accessed via
   SQLAlchemy models and Alembic migrations. That schema does not exist
   yet: `services/control-plane/src/control_plane/db/` is still an empty
   Phase 0 scaffold, and standing up the actual Postgres instance
   (`infra/docker-compose`) is explicitly Phase 4 work, not Phase 2 work.

Phase 2 cannot wait for Phase 4's infrastructure, and cannot violate
ADR-0003 to work around that. It needs a real, working interface today.

## Decision

The data-plane discovery CLI (`python -m data_plane.discovery.cli`) writes
its output as a JSON file: a plain array of `CatalogEntry` objects (the
shared `libs/contracts` shape — see `catalog.py`), written by
`data_plane.discovery.catalog_builder.write_catalog`.

The control plane reads that file through
`control_plane.catalog.CatalogRepository`, configured by a plain file path
(`TDM_CONTROL_PLANE_CATALOG_PATH`, default
`data/tmp/synthetic-estate/catalog.json` — matching the reference-data
estate's own default output location and the repository's `**/data/tmp/`
`.gitignore` rule). The repository lazy-loads and caches the file, and
exposes `reload()` for picking up a new discovery run without restarting
the process. `services/control-plane/src/control_plane/api/v1/catalog.py`
serves it: `GET /api/v1/catalog` (filterable list), `GET
/api/v1/catalog/summary`, `GET /api/v1/catalog/datasets`, and `GET
/api/v1/catalog/{source_system}/{dataset}/{column}`.

Critically, **no control-plane code imports `data_plane`**. The only
coupling between the two planes is the typed `CatalogEntry`/
`ColumnClassification` contract in `libs/contracts`, which each plane
depends on independently — exactly what ADR-0003 requires. Each side
happens to contain a few lines of near-identical JSON-parsing code
(`data_plane.discovery.catalog_builder.load_catalog` and
`control_plane.catalog.repository.CatalogRepository._ensure_loaded`)
rather than one shared function, because sharing that function would mean
one of the two service packages importing the other.

## Consequences

- **Works today, with zero new infrastructure.** A single-writer
  (discovery CLI run), single-reader (control plane process), local/dev
  setup works correctly and is exercised end to end by this phase's tests
  (`services/control-plane/tests/test_catalog_api.py`,
  `services/data-plane/tests/discovery/test_cli.py`).
- **Not a concurrency-safe, multi-writer design.** There is no locking
  story if two discovery runs write the file at once, and the control
  plane's in-memory cache (`CatalogRepository`) requires an explicit
  `reload()` — it will not notice a new file on disk automatically. Fine
  for this phase's scope (a portfolio/teaching project, one discovery run
  at a time); tracked as an explicit open item, `problems_phase_02.md`
  P2-4.
- **A small amount of duplicated logic** (JSON parsing into
  `CatalogEntry`) exists in both `data_plane.discovery.catalog_builder`
  and `control_plane.catalog.repository`. This is the deliberate cost of
  not sharing an in-process function across the plane boundary — the same
  tradeoff ADR-0003 already accepted for the whole system ("more upfront
  design work: every cross-plane interaction needs an explicit contract
  ... instead of a convenient shared in-process function call").
- **Superseded, not final.** Once the real metadata-plane PostgreSQL
  schema exists (a later phase — see `problems_phase_02.md` P2-4), the
  classification store should move there, per `DATA_GOVERNANCE.md` B.1
  ("tracked in the metadata plane's classification store"), and
  `CatalogRepository` should become a thin SQLAlchemy-backed repository
  instead of a JSON-file reader. Its public method signatures
  (`list_entries`, `get_entry`, `list_datasets`, `summary`) are written to
  make that swap possible without changing `api/v1/catalog.py` at all —
  the route handlers depend only on those methods, not on how they're
  implemented.
