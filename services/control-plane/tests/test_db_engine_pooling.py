"""Regression tests for `problems_final_review.md` P2-1 -- the
control-plane's Postgres engine now carries real connection-pool
resilience configuration (`pool_pre_ping`, bounded `pool_size`/
`max_overflow`, `pool_recycle`) instead of a bare
``create_engine(database_url)``.

These tests never open a real network connection (no Postgres server
runs in this environment) -- they only assert on the `Engine`/`Pool`
object's own configuration, which SQLAlchemy sets synchronously at
`create_engine()` time, before any connection is attempted.
"""

from __future__ import annotations

from control_plane.db.models import create_postgres_engine, create_sqlite_engine
from control_plane.db.session import get_engine_for_url


POSTGRES_URL = "postgresql+psycopg://tdm:tdm@localhost:5432/tdm_metadata_test"


def test_create_postgres_engine_enables_pre_ping_and_pool_bounds() -> None:
    engine = create_postgres_engine(POSTGRES_URL)
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
        assert engine.pool._recycle == 1800
    finally:
        engine.dispose()


def test_get_engine_for_url_applies_the_same_pool_config_for_postgres_urls() -> None:
    get_engine_for_url.cache_clear()
    engine = get_engine_for_url(POSTGRES_URL)
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
        assert engine.pool._recycle == 1800
    finally:
        engine.dispose()
        get_engine_for_url.cache_clear()


def test_sqlite_engines_are_unaffected_by_the_postgres_pool_config(tmp_path) -> None:
    # SQLite has no server-side staleness failure mode -- the Postgres-only
    # `pool_pre_ping`/`pool_size`/`max_overflow`/`pool_recycle` values must
    # not be forced onto it. `pool_pre_ping` defaults to `False` and
    # `pool_recycle` defaults to `-1` (never recycle) when not explicitly
    # requested, unlike the Postgres engines above which explicitly set
    # `pool_pre_ping=True`/`pool_recycle=1800`.
    sqlite_engine = create_sqlite_engine(str(tmp_path / "pool_test.db"))
    try:
        assert sqlite_engine.pool._pre_ping is False
        assert sqlite_engine.pool._recycle == -1
    finally:
        sqlite_engine.dispose()

    get_engine_for_url.cache_clear()
    sqlite_url = f"sqlite:///{tmp_path / 'pool_test2.db'}"
    session_engine = get_engine_for_url(sqlite_url)
    try:
        assert session_engine.pool._pre_ping is False
        assert session_engine.pool._recycle == -1
    finally:
        session_engine.dispose()
        get_engine_for_url.cache_clear()
