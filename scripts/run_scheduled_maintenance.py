#!/usr/bin/env python
"""A real, runnable entry point for the two periodic maintenance jobs
`docs/problems/problems_final_review.md` P2-3 named as having "no automatic trigger"
(tracked since `docs/problems/problems_phase_07.md` P7-3 and `docs/problems/problems_phase_08.md`
P8-3): the retention sweep (`LifecycleRepository.apply_retention`) and
vacuum-candidate identification (`CapacityPlanner.vacuum_candidates`).

Why this closes the gap without pretending to be a real scheduler
--------------------------------------------------------------------
Before this script, `apply_retention`/`vacuum_candidates` were real,
correct, callable methods with *no caller anywhere in the repository* --
not even a manual one. That was the actual gap: not "no Airflow DAG"
(deliberately out of scope, per ADR-0012 and `RefreshOrchestrator`'s own
module docstring), but "no way to run this periodically at all, by any
means." This script is that means: a single, real, idempotent Python
entry point with a plain exit code and machine-readable stdout (JSON),
exactly the shape a `cron` entry, a Kubernetes `CronJob`, or an Airflow
`PythonOperator`/`BashOperator` task would invoke on a schedule --

    # crontab -- run once an hour
    0 * * * * cd /path/to/repo/services/control-plane && python ../../scripts/run_scheduled_maintenance.py

    # Kubernetes CronJob (see infra/k8s for the Helm chart this would
    # sit alongside): command: ["python", "scripts/run_scheduled_maintenance.py"]

This deliberately does NOT ship a cron/Kubernetes-CronJob manifest of
its own -- that would be infrastructure this repository has no running
cluster to actually exercise (the same "no real cloud credentials"
boundary `docs/AZURE_PRODUCTION_DEPLOYMENT.md` and ADR-0017 already draw
for Spark/Delta). What is real and exercised here: the Python entry
point itself, its exit code, and its JSON summary -- see
`services/control-plane/tests/test_run_scheduled_maintenance.py` for the
executed proof.

Also acquires `control_plane.platform.scheduler_lock`'s real sweep lock
(P2-2) before running the retention sweep, under the same lock name
`POST /api/v1/lifecycle/scheduler/run-due` uses -- a cron-triggered
maintenance run and an API-triggered refresh sweep must not be allowed
to race each other either.

Vacuum-candidate identification never deletes anything (P8-3's own
scope boundary, restated in `docs/problems/problems_final_review.md` P2-5: no storage
adapter exists to actually delete an object from). This script only
*identifies and reports* candidates -- the same, honest, non-destructive
scope `CapacityPlanner.vacuum_candidates`'s own docstring already
promises.

Usage::

    cd services/control-plane   # or set PYTHONPATH so control_plane is importable
    python ../../scripts/run_scheduled_maintenance.py [--database-url sqlite:///...]
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone

from control_plane.config import get_settings
from control_plane.db.session import build_session_factory, get_engine_for_url, session_scope
from control_plane.domain.capacity.planner import CapacityPlanner
from control_plane.domain.lifecycle.repository import LifecycleRepository
from control_plane.domain.lifecycle.scheduler import LocalRefreshOrchestrator
from control_plane.platform.scheduler_lock import SchedulerLockHeldError, scheduler_sweep_lock


@dataclass
class MaintenanceRunSummary:
    """A plain, JSON-serializable summary of one maintenance run --
    returned by :func:`run_maintenance` and printed as this script's
    stdout, so a real cron/CronJob's log capture has a structured record
    of what happened without needing to parse prose."""

    as_of: datetime
    refresh_attempted: int
    refresh_succeeded: int
    refresh_failed: int
    retention_expired_version_ids: list[str] = field(default_factory=list)
    vacuum_candidate_version_ids: list[str] = field(default_factory=list)
    vacuum_candidate_reclaimable_bytes: int = 0
    skipped_due_to_lock: bool = False

    def to_json(self) -> str:
        return json.dumps(
            {
                "as_of": self.as_of.isoformat(),
                "refresh_attempted": self.refresh_attempted,
                "refresh_succeeded": self.refresh_succeeded,
                "refresh_failed": self.refresh_failed,
                "retention_expired_version_ids": self.retention_expired_version_ids,
                "vacuum_candidate_version_ids": self.vacuum_candidate_version_ids,
                "vacuum_candidate_reclaimable_bytes": self.vacuum_candidate_reclaimable_bytes,
                "skipped_due_to_lock": self.skipped_due_to_lock,
            },
            indent=2,
        )


def run_maintenance(
    session, *, as_of: datetime | None = None, triggered_by: str = "scheduled-maintenance"
) -> MaintenanceRunSummary:
    """Run the due-refresh sweep, the retention sweep, and
    vacuum-candidate identification once, against `session`. Returns a
    summary rather than raising when the sweep lock is already held
    (e.g. an API-triggered `run-due` call is in progress) -- a
    maintenance run finding the lock held simply skips this cycle and
    reports that, exactly like a real cron job that finds a previous
    invocation still running should back off rather than error loudly."""

    as_of = as_of or datetime.now(timezone.utc)
    repository = LifecycleRepository(session)

    try:
        with scheduler_sweep_lock(session, acquired_by=triggered_by):
            orchestrator = LocalRefreshOrchestrator(repository)
            sweep = orchestrator.run_due_refreshes(as_of, triggered_by=triggered_by)
            expired = repository.apply_retention(as_of=as_of)
            session.commit()
    except SchedulerLockHeldError:
        return MaintenanceRunSummary(
            as_of=as_of,
            refresh_attempted=0,
            refresh_succeeded=0,
            refresh_failed=0,
            skipped_due_to_lock=True,
        )

    planner = CapacityPlanner(repository)
    vacuum_candidates = planner.vacuum_candidates()

    return MaintenanceRunSummary(
        as_of=as_of,
        refresh_attempted=len(sweep.attempted),
        refresh_succeeded=len(sweep.results),
        refresh_failed=len(sweep.errors),
        retention_expired_version_ids=[str(v.version_id) for v in expired],
        vacuum_candidate_version_ids=[str(c.version_id) for c in vacuum_candidates],
        vacuum_candidate_reclaimable_bytes=sum(c.reclaimable_bytes for c in vacuum_candidates),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--database-url",
        default=None,
        help="Override the lifecycle database URL (defaults to the same "
        "TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL the API itself resolves).",
    )
    args = parser.parse_args(argv)

    database_url = args.database_url or get_settings().lifecycle_database_url
    engine = get_engine_for_url(database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        summary = run_maintenance(session)

    print(summary.to_json())
    return 0


if __name__ == "__main__":
    sys.exit(main())
