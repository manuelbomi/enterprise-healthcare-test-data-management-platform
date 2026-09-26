# ADR-0012: A narrow `RefreshOrchestrator` interface, not an Airflow/Databricks integration

## Status

Accepted

## Context

`ROADMAP.md` Phase 7 (dataset lifecycle and refresh management) asks for
"orchestration abstraction compatible with future Airflow, Databricks
Workflows or cloud schedulers." Two bad options were available:

1. **Build nothing** -- hardcode "how a refresh gets triggered" directly
   into the API layer, with no seam a future scheduler could plug into
   without rewriting the domain logic.
2. **Fake it** -- add an `airflow` dependency and a DAG file that looks
   like a real integration but has no Airflow instance to actually run
   against in this environment, giving a false impression of
   completeness a portfolio reviewer (or a future engineer) would
   eventually discover and distrust.

Neither is honest or useful. What a real scheduler integration actually
needs, at the seam where it meets application code, is small: a way to
ask "what needs to run right now?" and a way to say "run this one
thing." Everything else (cron expressions, DAG definitions, retries,
distributed execution, UI) is the scheduler's own job, not this
platform's.

## Decision

Define `control_plane.domain.lifecycle.scheduler.RefreshOrchestrator` as
an `ABC` with exactly two methods:

- `due_refreshes(as_of) -> list[EnvironmentDatasetRequest]` -- every
  ACTIVE environment request whose `next_refresh_at <= as_of`. This is
  the read side any scheduler needs to decide what to run.
- `run_due_refreshes(as_of, triggered_by) -> RefreshSweepResult` --
  actually executes a `SCHEDULED` refresh (via `LifecycleRepository.refresh`)
  for every due request, isolating one request's failure from the
  others (the same principle a real per-request Airflow task or
  Databricks Workflow job would apply on its own).

`LocalRefreshOrchestrator` is the one concrete implementation: a real,
in-process query and sweep executor against the Phase 7 schema (SQLite
locally, Postgres-portable). It is exposed over HTTP as
`GET /api/v1/lifecycle/scheduler/due` and
`POST /api/v1/lifecycle/scheduler/run-due` so an *external* scheduler
process (which is what Airflow/Databricks/a cloud scheduler actually
is -- a separate process that decides *when*) can poll/trigger it
without needing in-process Python access to this service.

### How a future Airflow DAG would plug into this

An Airflow DAG would not reimplement any refresh logic. It would have
one task (a `PythonOperator` or an `HttpOperator`) on a `@daily` (or
finer) schedule that either:

- calls `GET /api/v1/lifecycle/scheduler/due` and fans out one
  downstream task per due request (each calling
  `POST /api/v1/lifecycle/environment-requests/{id}/refresh` with
  `trigger=scheduled`), giving Airflow's own retry/alerting semantics
  per request, or
- calls `POST /api/v1/lifecycle/scheduler/run-due` directly and lets
  this service's own sweep (via `LocalRefreshOrchestrator`) handle the
  fan-out and per-request isolation, trading Airflow-level per-request
  observability for a simpler DAG.

Either way, Airflow's *only* job is deciding when the task runs (its
schedule) and what to do if the HTTP call itself fails (its retry
policy) -- it never needs to know anything about cadence math, dataset
versions, or the lifecycle schema. A Databricks Workflow would look
identical, substituting a Workflow job/task for an Airflow DAG/task. A
plain cloud scheduler (e.g. a Kubernetes CronJob calling `curl -X POST
.../scheduler/run-due`) is the simplest possible instance of the same
seam.

### What this deliberately does not include

- No Airflow/Databricks SDK dependency anywhere in this repository.
- No DAG file, no Workflow job definition, no cron expression parser.
- No retry/backoff policy of its own -- that is the scheduler's job, not
  `RefreshOrchestrator`'s. `RefreshSweepResult.errors` reports failures;
  it does not retry them.
- No distributed locking / exactly-once guarantee across multiple
  scheduler instances calling `run-due` concurrently -- a real
  production deployment would need the scheduler itself (Airflow's own
  single-active-DAG-run semantics, or a Kubernetes CronJob's
  `concurrencyPolicy: Forbid`) to prevent overlapping sweeps; this
  repository does not implement that itself. Tracked as an open item in
  `docs/problems/problems_phase_07.md`.

## Consequences

- The seam is real and independently testable
  (`services/control-plane/tests/test_lifecycle_repository.py`'s
  `LocalRefreshOrchestrator` tests, `test_lifecycle_api.py`'s
  `/scheduler/due` and `/scheduler/run-due` tests) without needing any
  external scheduler running in this environment.
- A future phase that adds a real Airflow/Databricks Workflow deployment
  only needs to write the DAG/Workflow definition itself -- the
  application-side contract it calls into already exists and is proven
  correct.
- The honest cost: this ADR is a documented promise about a shape, not a
  working Airflow deployment. Anyone evaluating this repository should
  read this ADR *as* the answer to "is there real Airflow integration
  here," not as a placeholder for one that secretly exists elsewhere.
