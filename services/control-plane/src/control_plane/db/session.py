"""Session management for the metadata plane's dataset lifecycle schema
(`control_plane.db.models`).

A thin wrapper around SQLAlchemy's `sessionmaker`, with a FastAPI-style
`session_scope` generator so route handlers (`control_plane.api.v1.lifecycle`)
and tests can share the exact same "open a session, yield it, close it"
pattern without duplicating engine-setup code.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from control_plane.db.models import init_schema


@lru_cache(maxsize=128)
def get_engine_for_url(database_url: str) -> Engine:
    """One cached `Engine` per distinct `database_url` for the lifetime
    of the process -- avoids re-opening a fresh SQLite file (and
    re-running `init_schema`) on every request while still letting tests
    point at a different URL per test (each distinct URL gets its own
    cache entry; `get_engine_for_url.cache_clear()` resets between test
    modules if needed).

    For a file-based SQLite URL (`sqlite:///path/to/file.db`), the
    parent directory is created first -- SQLite does not create it for
    you, unlike `postgresql+psycopg://...` DSNs which point at an
    already-running server.
    """

    if database_url.startswith("sqlite:///") and database_url != "sqlite:///:memory:":
        db_path = database_url.removeprefix("sqlite:///")
        if db_path:
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    if database_url.startswith("sqlite"):
        return create_engine(database_url)
    # Real (non-SQLite, i.e. Postgres) DSN: apply the same pool
    # resilience configuration as `control_plane.db.models.create_postgres_engine`
    # (`problems_final_review.md` P2-1) -- `pool_pre_ping` detects a
    # connection that has gone stale server-side before it is handed to
    # a caller, rather than surfacing that failure inside a request.
    return create_engine(
        database_url,
        pool_pre_ping=True,
        pool_size=5,
        max_overflow=10,
        pool_recycle=1800,
    )


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    """Create the schema (if needed) and return a session factory bound
    to `engine`. Calling this more than once against the same engine is
    safe -- `init_schema` is idempotent."""

    init_schema(engine)
    return sessionmaker(bind=engine, expire_on_commit=False)


@contextmanager
def session_scope(session_factory: sessionmaker[Session]) -> Iterator[Session]:
    """Yield a `Session`, committing on clean exit and rolling back on
    exception -- the standard SQLAlchemy unit-of-work pattern, shared by
    the FastAPI dependency (`api/v1/lifecycle.py`) and any script/test
    that needs one session per logical operation."""

    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


__all__ = ["build_session_factory", "get_engine_for_url", "session_scope"]
