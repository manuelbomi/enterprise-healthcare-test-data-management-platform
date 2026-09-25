"""The orchestration abstraction: a `RefreshOrchestrator` interface that
is deliberately narrow enough to be implemented by an in-process query
today and by Airflow, Databricks Workflows, or a cloud scheduler later,
without changing any caller of the interface.

Why this seam exists
---------------------
`ROADMAP.md` Phase 7 asks for "orchestration abstraction compatible with
future Airflow, Databricks Workflows or cloud schedulers" -- explicitly
*not* a fake Airflow integration. The honest scope here: build the one
seam a real scheduler would actually need (a "what needs refreshing
right now" query, and a way to execute exactly one refresh once told
to), implement it for real against this phase's own database (SQLite
locally, Postgres-portable), and document -- not fake -- how a future
DAG/Workflow plugs into the same interface. See
`docs/adr/0012-refresh-orchestration-abstraction.md` for the full
reasoning and the concrete "how Airflow would call this" walkthrough.

The interface
-------------
`RefreshOrchestrator` has exactly two methods:

- `due_refreshes(as_of)` -- every `EnvironmentDatasetRequest` whose
  `next_refresh_at <= as_of` and whose status is ACTIVE. This is the
  read side any scheduler (a cron-like loop, an Airflow sensor, a
  Databricks Workflow trigger) needs to decide "what should I run right
  now?"
- `run_due_refreshes(as_of, triggered_by)` -- actually executes a
  SCHEDULED refresh (via `LifecycleRepository.refresh`) for every
  request `due_refreshes` returns, and reports what happened. This is
  the seam a real scheduler's task/operator would call from inside its
  own execution unit (an Airflow task, a Databricks Workflow job) --
  the scheduler owns *when* this runs, this abstraction owns *what
  running it means*.

Neither method talks to Airflow/Databricks/a cloud scheduler's API --
that integration is future work, deliberately out of this phase's scope
(a fake integration would be worse than no integration, since it would
look real without being real). What's real is the interface and the one
concrete implementation behind it.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime, timezone

from healthcare_tdm_contracts import EnvironmentDatasetRequest, RefreshRunRecord, RefreshTrigger

from control_plane.domain.lifecycle.repository import LifecycleRepository
from control_plane.platform.dead_letter import DeadLetterStore


@dataclass
class RefreshSweepResult:
    """The outcome of one `run_due_refreshes` call: every request that
    was due, and the `RefreshRunRecord` produced for each (or `None` if
    that one request's refresh failed -- a failure for one request must
    never abort the sweep for the others, the same "isolate failures"
    principle a real Airflow task-per-request DAG would apply)."""

    as_of: datetime
    attempted: list[EnvironmentDatasetRequest]
    results: list[RefreshRunRecord]
    errors: dict[str, str]  # request_id (str) -> error message, for any that failed


class RefreshOrchestrator(ABC):
    """The orchestration abstraction every scheduler backend implements.

    A future `AirflowRefreshOrchestrator` or
    `DatabricksWorkflowsRefreshOrchestrator` would implement the same two
    methods, typically by *delegating* `run_due_refreshes` to
    `LocalRefreshOrchestrator` (or directly to `LifecycleRepository`)
    from inside a DAG task/Workflow job, while `due_refreshes` becomes
    the query an Airflow sensor or a Databricks Workflow trigger polls.
    See the module docstring and ADR-0012.
    """

    @abstractmethod
    def due_refreshes(self, as_of: datetime | None = None) -> list[EnvironmentDatasetRequest]:
        """Every ACTIVE `EnvironmentDatasetRequest` whose `next_refresh_at`
        is set and `<= as_of` (defaults to now, UTC)."""

    @abstractmethod
    def run_due_refreshes(
        self, as_of: datetime | None = None, *, triggered_by: str = "scheduler"
    ) -> RefreshSweepResult:
        """Execute a SCHEDULED refresh for every request `due_refreshes`
        returns. Must not let one request's failure prevent the others
        from being attempted."""


class LocalRefreshOrchestrator(RefreshOrchestrator):
    """A real, in-process implementation: a cron-like "what needs
    refreshing now" query plus a sweep executor, both backed directly by
    `LifecycleRepository` (and therefore the same SQLite/Postgres-portable
    schema every other part of this phase uses).

    This is what a local dev loop, a test, or a simple `cron`/Windows
    Task Scheduler entry would call directly. It is also exactly what a
    future Airflow `PythonOperator` or Databricks Workflow notebook task
    would call *from inside* its own scheduled execution -- the
    scheduler decides *when*, this class decides *what happens when it
    does*. See ADR-0012.
    """

    def __init__(self, repository: LifecycleRepository) -> None:
        self._repository = repository

    def due_refreshes(self, as_of: datetime | None = None) -> list[EnvironmentDatasetRequest]:
        as_of = as_of or datetime.now(timezone.utc)
        return self._repository.list_due_refreshes(as_of)

    def run_due_refreshes(
        self, as_of: datetime | None = None, *, triggered_by: str = "scheduler"
    ) -> RefreshSweepResult:
        as_of = as_of or datetime.now(timezone.utc)
        due = self.due_refreshes(as_of)
        results: list[RefreshRunRecord] = []
        errors: dict[str, str] = {}
        # Phase 11: in addition to isolating one request's failure from
        # the sweep (unchanged from Phase 7), a failure is now also
        # durably recorded -- see `control_plane.platform.dead_letter`'s
        # module docstring for why `RefreshSweepResult.errors` alone
        # (an in-memory dict returned to one caller) was not a real
        # dead-letter concept.
        dead_letters = DeadLetterStore(self._repository.session)
        for request in due:
            try:
                run = self._repository.refresh(
                    request.request_id,
                    trigger=RefreshTrigger.SCHEDULED,
                    triggered_by=triggered_by,
                )
                results.append(run)
            except Exception as exc:  # noqa: BLE001 -- isolate one request's failure from the sweep
                errors[str(request.request_id)] = str(exc)
                dead_letters.record(
                    event_type="scheduled_refresh_failed",
                    subject=str(request.request_id),
                    reason=str(exc),
                    payload={
                        "environment": request.environment.value,
                        "dataset_name": request.dataset_name,
                        "triggered_by": triggered_by,
                    },
                )
        return RefreshSweepResult(as_of=as_of, attempted=due, results=results, errors=errors)


__all__ = ["LocalRefreshOrchestrator", "RefreshOrchestrator", "RefreshSweepResult"]
