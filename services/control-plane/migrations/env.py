"""Alembic environment for `services/control-plane` (Phase 18A --
resolves `problems_final_review.md` P1-3).

Before this phase, the *only* schema-management mechanism in this
service was `control_plane.db.models.init_schema` (a bare
`Base.metadata.create_all(engine)`), which can create tables that don't
exist yet but cannot alter an existing table once a database already
has rows in it -- no supported way to add/rename/drop a column or
change a type across a real upgrade. This module wires Alembic (already
a declared dependency in `pyproject.toml`, previously unused) to the
same `Base.metadata` `init_schema` uses, so `alembic revision
--autogenerate` can detect real schema drift going forward.

`init_schema`/`create_all` is NOT removed by this phase -- tests and
local dev still use it (a fresh SQLite file created from scratch every
run has nothing to "migrate" from); it remains documented in
`control_plane.db.models`'s own module docstring as the from-scratch
path. Alembic is the tool for evolving a database that already has
real rows in it, which `create_all` was never designed to do.
"""

from __future__ import annotations

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

from control_plane.config import get_settings
from control_plane.db.models import Base

config = context.config

if config.config_file_name is not None:
    # `disable_existing_loggers=False` is deliberate, not the default:
    # `logging.config.fileConfig`'s default (`True`) permanently sets
    # `.disabled = True` on every OTHER logger that already exists in
    # the process at the moment this runs (e.g. `control_plane.request`,
    # created at `control_plane.main` import time) and is not itself
    # named in this ini's `[loggers]` section -- a classic footgun for
    # any application that might run Alembic from within a longer-lived
    # process (or, as `services/control-plane/tests/test_migrations.py`
    # discovered, in the same pytest process as
    # `test_platform_logging.py`'s real logging tests). Without this,
    # every log line this service's own Phase 18A observability work
    # (`control_plane.platform.logging_config`) emits after the first
    # `alembic upgrade`/`downgrade` call in a process would silently,
    # permanently stop being emitted.
    fileConfig(config.config_file_name, disable_existing_loggers=False)

#: The single source of truth for every table this service owns --
#: exactly what `control_plane.db.models.init_schema` calls
#: `Base.metadata.create_all` against. Autogenerate compares the live
#: database against this.
target_metadata = Base.metadata


def _resolve_database_url() -> str:
    """Resolution order: an explicit `-x db_url=<url>` CLI override (for
    pointing a one-off migration run at a non-default database without
    touching environment variables), then the same
    `TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL` environment variable (via
    `control_plane.config.Settings`) the running application itself
    resolves -- so `alembic upgrade head` always targets the same
    database the application would connect to, never a second,
    independently-configured URL that could silently drift from it."""

    x_args = context.get_x_argument(as_dictionary=True)
    override = x_args.get("db_url")
    if override:
        return override
    return get_settings().lifecycle_database_url


def run_migrations_offline() -> None:
    """Emit SQL to stdout without a live DB connection (`alembic upgrade
    head --sql`) -- useful for a real deployment's change-review process
    (review the exact DDL before it runs against production)."""

    url = _resolve_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a real, live database connection -- the
    normal `alembic upgrade head` path."""

    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _resolve_database_url()
    connectable = engine_from_config(configuration, prefix="sqlalchemy.", poolclass=pool.NullPool)

    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
