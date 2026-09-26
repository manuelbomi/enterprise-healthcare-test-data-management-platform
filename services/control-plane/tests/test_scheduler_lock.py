"""Regression tests for `docs/problems/problems_final_review.md` P2-2 --
`control_plane.platform.scheduler_lock` gives concurrent scheduler
sweeps a real, database-enforced mutual-exclusion lock instead of no
protection at all.

Two *separate* sessions (bound to the same on-disk SQLite file, exactly
the way two separate FastAPI worker processes/requests would each get
their own session against the same database) stand in for two
concurrent callers -- this is a real reproduction of the race, not a
same-session simulation."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from control_plane.db.models import SchedulerLockRow, create_sqlite_engine, init_schema
from control_plane.db.session import build_session_factory
from control_plane.platform.scheduler_lock import (
    DEFAULT_STALE_AFTER,
    LIFECYCLE_SCHEDULER_SWEEP_LOCK,
    SchedulerLockHeldError,
    scheduler_sweep_lock,
)


@pytest.fixture
def two_sessions(tmp_path: Path):
    engine = create_sqlite_engine(str(tmp_path / "scheduler_lock.db"))
    init_schema(engine)
    factory = build_session_factory(engine)
    session_a = factory()
    session_b = factory()
    yield session_a, session_b
    session_a.close()
    session_b.close()


def test_second_concurrent_sweep_is_refused_while_the_first_holds_the_lock(two_sessions) -> None:
    session_a, session_b = two_sessions

    with scheduler_sweep_lock(session_a, acquired_by="worker-a"):
        # Simulates a second process (a different session against the
        # same database) trying to start an overlapping sweep.
        with pytest.raises(SchedulerLockHeldError) as excinfo:
            with scheduler_sweep_lock(session_b, acquired_by="worker-b"):
                pytest.fail("should never enter the guarded block")
        assert excinfo.value.held_by == "worker-a"

    # Released cleanly on the way out of the first `with` -- a third,
    # non-overlapping caller succeeds.
    with scheduler_sweep_lock(session_b, acquired_by="worker-b"):
        pass


def test_lock_is_released_even_if_the_guarded_block_raises(two_sessions) -> None:
    session_a, session_b = two_sessions

    with pytest.raises(ValueError):
        with scheduler_sweep_lock(session_a, acquired_by="worker-a"):
            raise ValueError("simulated sweep failure")

    # The lock must not be left held by a crashed sweep.
    with scheduler_sweep_lock(session_b, acquired_by="worker-b"):
        pass


def test_a_stale_lock_is_taken_over_rather_than_wedging_forever(two_sessions) -> None:
    session_a, session_b = two_sessions

    # Simulate worker-a acquiring the lock and then crashing (never
    # releasing it) a long time ago.
    stale_row = SchedulerLockRow(
        lock_name=LIFECYCLE_SCHEDULER_SWEEP_LOCK,
        acquired_by="worker-a-crashed",
        acquired_at=datetime.now(timezone.utc) - (DEFAULT_STALE_AFTER + timedelta(minutes=1)),
    )
    session_a.add(stale_row)
    session_a.commit()

    # A fresh caller is not blocked forever by the abandoned lock.
    with scheduler_sweep_lock(session_b, acquired_by="worker-b"):
        pass


def test_a_fresh_lock_is_not_stolen(two_sessions) -> None:
    session_a, session_b = two_sessions

    fresh_row = SchedulerLockRow(
        lock_name=LIFECYCLE_SCHEDULER_SWEEP_LOCK,
        acquired_by="worker-a",
        acquired_at=datetime.now(timezone.utc),
    )
    session_a.add(fresh_row)
    session_a.commit()

    with pytest.raises(SchedulerLockHeldError):
        with scheduler_sweep_lock(session_b, acquired_by="worker-b"):
            pytest.fail("should never enter the guarded block")
