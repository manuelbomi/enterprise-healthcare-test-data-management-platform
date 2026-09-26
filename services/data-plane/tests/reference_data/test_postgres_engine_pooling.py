"""Regression tests for `docs/problems/problems_final_review.md` P2-1 -- mirrors
`services/control-plane/tests/test_db_engine_pooling.py`. The data
plane's `create_postgres_engine` now carries the same connection-pool
resilience configuration (`pool_pre_ping`, bounded `pool_size`/
`max_overflow`, `pool_recycle`) as the control plane's, instead of a
bare ``create_engine(database_url)``.

No real Postgres server runs in this environment -- these tests only
assert on the `Engine`/`Pool` object's own configuration, which
SQLAlchemy sets synchronously at `create_engine()` time.
"""

from __future__ import annotations

from data_plane.reference_data.postgres_models import (
    create_postgres_engine,
    create_sqlite_engine,
)


POSTGRES_URL = "postgresql+psycopg://tdm:tdm@localhost:5432/tdm_source_enrollment_test"


def test_create_postgres_engine_enables_pre_ping_and_pool_bounds() -> None:
    engine = create_postgres_engine(POSTGRES_URL)
    try:
        assert engine.pool._pre_ping is True
        assert engine.pool.size() == 5
        assert engine.pool._max_overflow == 10
        assert engine.pool._recycle == 1800
    finally:
        engine.dispose()


def test_sqlite_engine_is_unaffected_by_the_postgres_pool_config(tmp_path) -> None:
    sqlite_engine = create_sqlite_engine(str(tmp_path / "pool_test.db"))
    try:
        assert sqlite_engine.pool._pre_ping is False
        assert sqlite_engine.pool._recycle == -1
    finally:
        sqlite_engine.dispose()
