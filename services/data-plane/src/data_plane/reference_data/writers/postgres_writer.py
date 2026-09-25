"""PostgreSQL writer: the enrollment/eligibility + provider-directory system.

Thin wrapper around ``postgres_models.write_postgres_entities`` that
resolves a default local SQLite path under the generator's output root
(so running the generator requires no external infrastructure) while
still accepting a real PostgreSQL DSN override (``database_url``) for
running against ``infra/docker/docker-compose.yml``'s Postgres service
once it exists (Phase 4) -- see ``postgres_models.py`` for why the same
models/writer work unmodified against either engine.
"""

from __future__ import annotations

from pathlib import Path

from data_plane.reference_data.domain import (
    Address,
    Coverage,
    Member,
    MemberDemographics,
    Plan,
    Provider,
)
from data_plane.reference_data.postgres_models import (
    create_postgres_engine,
    create_sqlite_engine,
    write_postgres_entities,
)

DB_FILENAME = "enrollment.sqlite3"


def write_enrollment_system(
    output_root: Path,
    members: list[Member],
    demographics: list[MemberDemographics],
    addresses: list[Address],
    plans: list[Plan],
    coverages: list[Coverage],
    providers: list[Provider],
    database_url: str | None = None,
) -> str:
    """Write the enrollment/eligibility estate. Returns the resolved database URL."""

    if database_url:
        engine = create_postgres_engine(database_url)
        resolved_url = database_url
    else:
        bucket_dir = output_root / "postgres_enrollment"
        bucket_dir.mkdir(parents=True, exist_ok=True)
        db_path = bucket_dir / DB_FILENAME
        engine = create_sqlite_engine(str(db_path))
        resolved_url = f"sqlite:///{db_path}"

    write_postgres_entities(engine, members, demographics, addresses, plans, coverages, providers)
    return resolved_url


__all__ = ["DB_FILENAME", "write_enrollment_system"]
