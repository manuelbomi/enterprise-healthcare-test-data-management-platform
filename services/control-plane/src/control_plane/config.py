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


def get_settings() -> Settings:
    """Return process settings.

    A plain function (rather than a module-level singleton) so tests can
    override settings cleanly via dependency injection once the FastAPI
    app wires this in (Phase 2).
    """

    return Settings()
