# Chapter 13 — Snapshots and refresh cadence

## The concept

A **snapshot** is a named, versioned, point-in-time test dataset a team
can request and later refresh — the output of everything Chapters 5-12
built, given a durable identity and a lifecycle. Certification (Chapter
12) answers "is this dataset safe to use, right now." Snapshot lifecycle
management answers the next question: "which version of this dataset is
each environment actually using, when should it be refreshed to a newer
one, and what happens if we need to roll back." Without this layer, a
certified dataset is a one-shot pipeline output with no ongoing
identity — exactly the gap this repository's own `ARCHITECTURE.md`
notes: everything through certification is a data-plane *engine*
(read files, transform them, write files); this is the first capability
that is genuine **persistent, queryable state** — a database-backed
domain model, not another JSON artifact.

## The core design decision: one version, many environment pointers

`control_plane.domain.lifecycle`'s `DatasetVersion` is deliberately
**environment-agnostic** — it has no `target_environment` field.
`EnvironmentDatasetRequest` is a separate row, one per `(environment,
dataset_name)`, that points at a `DatasetVersion` via a foreign key.
Chapter 4 already showed the diagram; the concrete consequence is that
two, or five, environments requesting the same certified dataset get
multiple rows referencing the *same* `storage_uri`, never multiple
physical copies — the mechanism Chapter 15 (Capacity planning) measures
the savings from.

## Refresh cadence per environment, and what refreshing actually does

Each `(environment, dataset_name)` pair has a `RefreshPolicy`
(`RefreshCadenceType`: `weekly` / `biweekly` / `monthly` /
`release_driven` / `on_demand`). A refresh moves an environment's
pointer from one `DatasetVersion` to another — it does not touch the
version it's moving away from, and it does not silently move any other
environment.

## Revocation: a deliberate non-automation

If a `DatasetVersion` is revoked, no `EnvironmentDatasetRequest`
currently pointing at it is automatically moved. Two reasons this
repository documents explicitly: a silent forced migration mid-test-run
is its own operational risk, and visibility (an operator seeing the
revoked status and choosing the next action with full context) is the
correct first response, not automation guessing on the operator's
behalf. What revocation *does* enforce immediately, by code: no
mutation may newly *select* a revoked version going forward.

## Real, end-to-end output

`scripts/demo_phase7_lifecycle.py` runs the real Phase 6 certification
pipeline twice and exercises every lifecycle endpoint against a real
FastAPI `TestClient` backed by a real on-disk SQLite database. Real
captured output from `docs/tutorial/07-dataset-lifecycle-and-refresh.md`
(reproduced here because it already is real, verified output — see
`problems_phase_15.md` for why this guide doesn't re-run the same demo
script a second time just to get a second, equally-real transcript):

```
STEP 4 -- Confirm zero duplicate physical copies
DatasetVersion.storage_uri is referenced by: ['dev', 'qa', 'sit', 'uat', 'performance']
All 5 environments point at the SAME storage_uri: ...\phase7-demo\run-v1\masked

STEP 7 -- On-demand refresh: move DEV onto version 2
Refresh run: succeeded=True  detail=Refreshed to version 2
DEV now on version 2 (QA remains on version 1)

STEP 8 -- Roll DEV back to version 1
Rolled back DEV: from v2 -> v1
Version 2 status after rollback (unreferenced by any environment): rolled_back

STEP 9 -- Revoke version 1; confirm existing usage is undisturbed but new selection is blocked
Version 1 status: revoked
DEV's request is UNCHANGED (still points at revoked version 1)
Attempting to roll QA back to the now-revoked version 1: HTTP 409
```

Step 4 through Step 9 is the whole chapter, proven with a real run: one
physical dataset shared by five environments, a targeted refresh that
moves exactly one environment, a rollback, and a revocation that is
visible everywhere but disturbs nothing already in flight.

## The orchestration abstraction

`control_plane.domain.lifecycle.scheduler.RefreshOrchestrator` is a
two-method `ABC` (`due_refreshes`, `run_due_refreshes`);
`LocalRefreshOrchestrator` is the one real, in-process implementation,
exposed as `GET /api/v1/lifecycle/scheduler/due` and
`POST /api/v1/lifecycle/scheduler/run-due`. See
[ADR-0012](../../adr/0012-refresh-orchestration-abstraction.md) for how a
future Airflow DAG or Databricks Workflow would call the same two
endpoints from inside its own scheduled task, without this repository
having to fake that integration.

## Where to go next

Continue to [Chapter 14 — Storage techniques](14-storage-techniques.md),
or read `docs/tutorial/07-dataset-lifecycle-and-refresh.md` for the
complete API surface and every endpoint under `/api/v1/lifecycle`.
