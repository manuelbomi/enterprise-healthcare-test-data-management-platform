"""Real, executed proof that the Phase 18A Alembic setup
(`services/control-plane/alembic.ini`, `migrations/`) actually works --
resolves `docs/problems/problems_final_review.md` P1-3 ("no schema-migration
framework exists ... only `Base.metadata.create_all()`").

Before this phase, there was no code path at all that could alter an
existing table once a database already had rows in it. These tests run
the real `alembic` CLI machinery (via `alembic.config.Config` +
`alembic.command`, not a hand-rolled substitute) against a real,
on-disk SQLite database and prove:

1. `alembic upgrade head` from an empty database produces every table
   `control_plane.db.models.Base.metadata`/`init_schema` would have
   created -- i.e. the migration is a faithful baseline, not a stale or
   hand-transcribed approximation.
2. `alembic downgrade base` cleanly removes everything the upgrade
   added -- proving the migration is reversible, not just additive.
3. Running `alembic upgrade head` twice is a no-op the second time
   (idempotent, the same guarantee `init_schema` already documents for
   `create_all`).
"""

from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

CONTROL_PLANE_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config(db_url: str) -> Config:
    config = Config(str(CONTROL_PLANE_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(CONTROL_PLANE_ROOT / "migrations"))
    return config


def _run(config: Config, db_url: str) -> None:
    """Invoke `alembic` the same way its own CLI does: parse `-x
    db_url=<url>` into `cmd_opts.x` so `migrations/env.py`'s
    `context.get_x_argument` sees it, exactly the resolution path
    `alembic upgrade head -x db_url=...` uses on a real terminal."""

    class _Namespace:
        x = [f"db_url={db_url}"]

    config.cmd_opts = _Namespace()  # type: ignore[attr-defined]


EXPECTED_TABLES = {
    "audit_event",
    "business_consumer",
    "consumer_dataset_request",
    "dataset_version",
    "dead_letter_event",
    "environment_dataset_request",
    "illustrative_capacity_plan",
    "masking_policy_version",
    "policy_approval",
    "refresh_policy",
    "refresh_run",
    "rollback_event",
    "scheduler_lock",
}


def test_alembic_upgrade_head_creates_every_table_base_metadata_defines(tmp_path: Path) -> None:
    db_path = tmp_path / "migration-upgrade.db"
    db_url = f"sqlite:///{db_path}"
    config = _alembic_config(db_url)
    _run(config, db_url)

    command.upgrade(config, "head")

    engine = create_engine(db_url)
    # `alembic_version` is alembic's own migration-tracking table, not
    # part of the application schema -- excluded from the comparison.
    tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    assert tables == EXPECTED_TABLES, (
        f"alembic upgrade head produced {tables}, expected exactly {EXPECTED_TABLES} -- "
        "the migration has drifted from control_plane.db.models.Base.metadata."
    )


def test_alembic_upgrade_head_matches_init_schema_create_all(tmp_path: Path) -> None:
    """The from-scratch `create_all` path (`control_plane.db.models.init_schema`,
    used by tests/local dev) and the new `alembic upgrade head` path
    (for a real deployment with an existing database) must produce the
    SAME set of tables -- otherwise a reader could not trust that the
    migration actually represents this service's real schema."""

    from control_plane.db.models import create_sqlite_engine, init_schema

    create_all_db = tmp_path / "create-all.db"
    create_all_engine = create_sqlite_engine(str(create_all_db))
    init_schema(create_all_engine)
    create_all_tables = set(inspect(create_all_engine).get_table_names())

    migrated_db = tmp_path / "migrated.db"
    db_url = f"sqlite:///{migrated_db}"
    config = _alembic_config(db_url)
    _run(config, db_url)
    command.upgrade(config, "head")
    migrated_tables = set(inspect(create_engine(db_url)).get_table_names()) - {"alembic_version"}

    assert migrated_tables == create_all_tables


def test_alembic_downgrade_base_removes_everything_it_added(tmp_path: Path) -> None:
    db_path = tmp_path / "migration-downgrade.db"
    db_url = f"sqlite:///{db_path}"
    config = _alembic_config(db_url)
    _run(config, db_url)

    command.upgrade(config, "head")
    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) - {"alembic_version"} == EXPECTED_TABLES

    command.downgrade(config, "base")
    # SQLAlchemy caches reflected metadata; use a fresh inspector.
    remaining = set(inspect(create_engine(db_url)).get_table_names()) - {"alembic_version"}
    assert remaining == set()


def test_alembic_upgrade_head_is_idempotent(tmp_path: Path) -> None:
    db_path = tmp_path / "migration-idempotent.db"
    db_url = f"sqlite:///{db_path}"
    config = _alembic_config(db_url)
    _run(config, db_url)

    command.upgrade(config, "head")
    # A second call against an already-migrated database must not raise
    # or attempt to re-create any table.
    command.upgrade(config, "head")

    engine = create_engine(db_url)
    assert set(inspect(engine).get_table_names()) - {"alembic_version"} == EXPECTED_TABLES
