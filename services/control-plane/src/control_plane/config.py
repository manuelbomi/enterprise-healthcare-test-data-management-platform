"""Application configuration.

All configuration is read from environment variables (optionally via a
local .env file in development, never committed — see repository
.gitignore). No secret value ever has a real default here; defaults are
only provided for genuinely non-sensitive, local-dev-friendly settings.

Real deployments resolve secrets (e.g., the database password) through the
security/governance plane's secrets provider adapter, not by setting them
as plain environment variables in a production context — that adapter is
implemented in services/governance-service starting Phase 3. Locally,
environment variables are an acceptable stand-in for a full secrets
provider (see SECURITY.md).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Process-wide settings for the control plane service.

    Phase 0 note: this is a minimal placeholder set of fields sufficient
    to describe the shape of configuration. Fields will grow as each
    phase adds real behavior (database connectivity in Phase 1, storage
    adapters in Phase 5, etc.).
    """

    model_config = SettingsConfigDict(env_prefix="TDM_CONTROL_PLANE_", env_file=".env")

    environment: str = "local"
    log_level: str = "INFO"
    database_url: str = "postgresql+psycopg://tdm:tdm@localhost:5432/tdm_metadata"
    api_v1_prefix: str = "/api/v1"
    # Path to the PHI/PII data catalog JSON artifact the data-plane
    # discovery engine (`data_plane.discovery.cli`) writes. Read by
    # `control_plane.catalog.CatalogRepository` and served by
    # `api/v1/catalog.py`. See ADR-0009
    # (`docs/adr/0009-catalog-artifact-handoff.md`) for why this is a file
    # path rather than a database connection in Phase 2.
    catalog_path: str = "data/tmp/synthetic-estate/catalog.json"
    # SQLAlchemy database URL for the Phase 7 dataset lifecycle schema
    # (`control_plane.db.models`). Defaults to a local SQLite file --
    # zero infrastructure required, consistent with Phase 1's
    # `data_plane.reference_data` approach -- but the schema itself is
    # Postgres-portable (no JSONB/native UUID columns); pointing this at
    # a real `postgresql+psycopg://...` DSN (per ADR-0004) works
    # unmodified. See `problems_phase_07.md` for what remains unverified
    # against a real Postgres instance.
    lifecycle_database_url: str = "sqlite:///data/tmp/control-plane/lifecycle.db"
    # Phase 9: read-only JSON-artifact roots for the data-plane engines
    # that do not yet have their own control-plane API (masking,
    # subsetting, synthetic scenario generation, certification -- see
    # ARCHITECTURE.md's Phase 3/4/5/6 notes). Each repository under
    # `control_plane.artifacts` recursively scans its configured root for
    # the well-known artifact filename a data-plane CLI/pipeline run
    # writes (e.g. `certification_report.json`), exactly the same
    # single-writer/single-reader JSON-artifact-handoff pattern ADR-0009
    # established for the Phase 2 catalog -- no control-plane code here
    # imports `data_plane`.
    masking_artifacts_root: str = "data/tmp"
    subsetting_artifacts_root: str = "data/tmp"
    synthetic_artifacts_root: str = "data/tmp"
    certification_artifacts_root: str = "data/tmp"
    # Phase 9: CORS origins allowed to call this API cross-origin.
    # ADR-0008's default local-dev path is same-origin (the Vite dev
    # server proxies `/api` to this service -- see `frontend/vite.config.ts`
    # -- so the browser never makes a cross-origin request and no CORS
    # header is needed). This exists for the documented escape hatch
    # `frontend/.env.example`'s `VITE_API_BASE_URL` already describes
    # ("targets a control plane running somewhere else"), and for any
    # future deployment shape where the frontend is served from a
    # different origin than this API. Comma-separated; empty means no
    # CORS middleware is installed at all (the strictest default).
    cors_allowed_origins: str = ""

    @property
    def cors_allowed_origins_list(self) -> list[str]:
        return [origin.strip() for origin in self.cors_allowed_origins.split(",") if origin.strip()]


def get_settings() -> Settings:
    """Return process settings.

    A plain function (rather than a module-level singleton) so tests can
    override settings cleanly via dependency injection once the FastAPI
    app wires this in (Phase 2).
    """

    return Settings()
