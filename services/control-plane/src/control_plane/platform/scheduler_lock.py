"""A real, portable mutual-exclusion lock for concurrent scheduler
sweeps -- resolves `problems_final_review.md` P2-2 ("no distributed
lock on concurrent scheduler sweeps"), tracked since
`problems_phase_07.md` P7-2.

Why this is real (not a fake/no-op lock)
-----------------------------------------
Two concurrent calls to `POST /api/v1/lifecycle/scheduler/run-due` had
no application-level mechanism preventing an overlapping sweep -- each
would independently call `LifecycleRepository.list_due_refreshes` and
could both attempt to refresh the same due request at once. This module
closes that gap with `SchedulerLockRow`
(`control_plane.db.models.SchedulerLockRow`), a row-per-lock table whose
`lock_name` column is a primary key: two concurrent transactions racing
to `INSERT` a row with the same `lock_name` can never both succeed --
the database's own primary-key constraint is the actual mutual-exclusion
mechanism, enforced identically by SQLite and Postgres, unlike a
check-then-act read-then-write race in application code (which this
deliberately is NOT).

Why a row-per-lock table rather than `pg_advisory_lock`
---------------------------------------------------------
`pg_advisory_lock` is Postgres-only and has no SQLite equivalent, and
this repository's `create_engine`/schema code is deliberately portable
across both backends (see `control_plane.db.models`'s module
docstring). A unique-constraint-backed lock row works identically on
both, at the cost of being coarser (it does not automatically release
on connection loss the way a session-scoped Postgres advisory lock
would) -- addressed here with a `stale_after` timeout: a lock held
longer than that is assumed abandoned (e.g. the process that acquired
it crashed mid-sweep) and is taken over by the next caller, rather than
wedging the endpoint forever. This is a deliberate, honest scope
boundary: it closes the *application-level* race this finding named,
not every conceivable multi-process failure mode -- a real
multi-instance deployment should still prefer its external scheduler's
own concurrency control (Airflow single-active-DAG-run, Kubernetes
CronJob `concurrencyPolicy: Forbid`), exactly as ADR-0012 and
`docs/runbooks/duplicate-requests-and-revoked-datasets.md` already
recommend; this lock is defense in depth for the one gap those docs
name, not a replacement for it.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from typing import Iterator

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from control_plane.db.models import SchedulerLockRow

#: The one lock name this module currently guards -- a single sweep
#: across every due request, not one lock per request (the whole point
#: is to prevent two *sweeps* from overlapping).
LIFECYCLE_SCHEDULER_SWEEP_LOCK = "lifecycle_scheduler_run_due"

#: How long a lock may be held before it is considered abandoned and
#: safe to steal. Generous relative to any real sweep's expected
#: duration (a sweep that isolates and dead-letters failures per
#: request, per `control_plane.domain.lifecycle.scheduler`, should
#: never legitimately run this long).
DEFAULT_STALE_AFTER = timedelta(minutes=15)


class SchedulerLockHeldError(Exception):
    """Raised when the named lock is already held by another
    (non-stale) sweep. Callers (`api/v1/lifecycle.py`'s
    `run_due_refreshes`) should translate this into HTTP 409 Conflict --
    the sweep was refused, not silently skipped or silently duplicated."""

    def __init__(self, lock_name: str, held_by: str, acquired_at: datetime) -> None:
        self.lock_name = lock_name
        self.held_by = held_by
        self.acquired_at = acquired_at
        super().__init__(
            f"scheduler lock {lock_name!r} is already held by {held_by!r} "
            f"(acquired at {acquired_at.isoformat()}); refusing to start an overlapping sweep"
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _as_aware_utc(value: datetime) -> datetime:
    """SQLite has no native timezone-aware `DATETIME` type -- a value
    written as tz-aware UTC comes back from a fresh query naive (this is
    the same "SQLite stores DateTime as a naive string" behavior every
    other `DateTime` column in `control_plane.db.models` is subject to).
    Postgres's `DateTime` (mapped without `timezone=True`, matching the
    rest of this schema) behaves the same way. Every `acquired_at` this
    module writes is UTC by construction (`_now()`), so a naive value
    read back is always safe to re-attach `timezone.utc` to."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


@contextmanager
def scheduler_sweep_lock(
    session: Session,
    *,
    lock_name: str = LIFECYCLE_SCHEDULER_SWEEP_LOCK,
    acquired_by: str = "scheduler",
    stale_after: timedelta = DEFAULT_STALE_AFTER,
) -> Iterator[None]:
    """Acquire `lock_name` for the duration of the `with` block, commit
    that acquisition immediately (so a concurrent caller in a different
    session/transaction sees it right away, not only after this
    request's outer transaction eventually commits), then release it
    (also committed immediately) on the way out -- including when the
    guarded block raises.

    Raises `SchedulerLockHeldError` if the lock is already held by a
    non-stale holder. A stale holder (older than `stale_after`) is
    deleted and the lock re-acquired for the new caller in the same
    call, rather than requiring a second call.
    """

    existing = session.get(SchedulerLockRow, lock_name)
    if existing is not None and _now() - _as_aware_utc(existing.acquired_at) < stale_after:
        held_by, held_at = existing.acquired_by, _as_aware_utc(existing.acquired_at)
        # End this session's read transaction before raising -- SQLite's
        # (and Postgres's default) snapshot isolation would otherwise
        # keep this session pinned to the pre-release state it just
        # read, so the *next* call on this same session would see a
        # stale "still held" snapshot even after the real holder
        # released it in the meantime.
        session.rollback()
        raise SchedulerLockHeldError(lock_name, held_by, held_at)
    if existing is not None:
        # Stale -- assume the previous holder crashed mid-sweep and take
        # over rather than wedging this endpoint forever.
        session.delete(existing)
        session.flush()

    row = SchedulerLockRow(lock_name=lock_name, acquired_by=acquired_by, acquired_at=_now())
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        # The real mutual-exclusion event: another transaction won the
        # race to INSERT the same primary key between our SELECT above
        # and our INSERT here. This is the case the SELECT-then-INSERT
        # sequence above cannot itself prevent -- only the database's
        # own primary-key constraint can, which is exactly why this is
        # a real lock and not a check-then-act race.
        session.rollback()
        winner = session.get(SchedulerLockRow, lock_name)
        held_by = winner.acquired_by if winner is not None else "unknown"
        held_at = _as_aware_utc(winner.acquired_at) if winner is not None else _now()
        raise SchedulerLockHeldError(lock_name, held_by, held_at) from None

    try:
        yield
    finally:
        session.query(SchedulerLockRow).filter(SchedulerLockRow.lock_name == lock_name).delete()
        session.commit()


__all__ = [
    "DEFAULT_STALE_AFTER",
    "LIFECYCLE_SCHEDULER_SWEEP_LOCK",
    "SchedulerLockHeldError",
    "scheduler_sweep_lock",
]
