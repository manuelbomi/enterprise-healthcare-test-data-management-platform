# Tutorial 07 — Dataset lifecycle and refresh management

This tutorial walks through real, runnable code:
`control_plane.domain.lifecycle` and `control_plane.api.v1.lifecycle`,
the first part of this platform that treats a certified test dataset as
a *product* with versions, environments, a refresh schedule, retention,
and a rollback/revocation story — not just a one-shot pipeline output.

## Why this is a control-plane phase, not another data-plane pipeline

Every phase so far (1-6) is a data-plane *engine*: something that reads
files, transforms them, and writes files, with a JSON artifact
(`catalog.json`, `subset_manifest.json`, `masking_run_summary.json`,
`certification_report.json`) as its interim hand-off to whichever plane
reads it next (see ADR-0009 for why that interim pattern exists). Phase
7 is different: "which dataset versions exist," "which environment is
on which version," and "when is the next refresh due" are not files
produced by a transformation — they are **persistent, queryable state**
that changes over time and that many callers (an API consumer, a
scheduler, an auditor) need to query independently of whether any
pipeline is currently running. That is exactly what
`ARCHITECTURE.md` section 2.3 says the metadata plane is for, and
exactly why this phase gives `services/control-plane` its first real,
database-backed domain model instead of writing yet another JSON file.

## The shapes

All defined in `healthcare_tdm_contracts.lifecycle`
(`libs/contracts/src/healthcare_tdm_contracts/lifecycle.py`):

| Contract | What it represents |
|---|---|
| `Environment` | `dev` / `qa` / `sit` / `uat` / `performance` |
| `RefreshCadenceType` | `weekly` / `biweekly` / `monthly` / `release_driven` / `on_demand` |
| `DatasetVersionStatus` | `active` / `expired` / `revoked` / `rolled_back` |
| `DatasetVersion` | one immutable, registered dataset artifact |
| `RefreshPolicy` | cadence + retention + grace period, per environment (and optionally per dataset) |
| `EnvironmentDatasetRequest` | one environment's standing pointer to a `DatasetVersion` |
| `RefreshRunRecord` | one execution of a refresh (scheduled or on-demand) |
| `RollbackRecord` | durable rollback metadata |

The database schema behind them
(`services/control-plane/src/control_plane/db/models.py`) follows the
exact portability pattern `data_plane.reference_data.postgres_models`
established in Phase 1: no `JSONB`, no native `UUID` column type, so the
same models work against local SQLite (what every test and this
tutorial use) and a real PostgreSQL DSN unmodified — only the connection
URL changes. See `problems_phase_07.md` for what remains unverified
against a real Postgres instance (same honest gap `problems_phase_01.md`
P1-1 documents for Phase 1's own Postgres-shaped tables).

## The core design decision: one dataset version, many environment pointers

`DatasetVersion` is deliberately **environment-agnostic** — it has no
`target_environment` field. `EnvironmentDatasetRequest` is a *separate*
row, one per `(environment, dataset_name)`, that points at a
`DatasetVersion` via a foreign key
(`current_version_id`). Two environments requesting the same dataset
therefore get **two rows that reference the same `storage_uri`**, never
two physical copies:

```
DatasetVersion(dataset_name="claims", version_number=3, storage_uri="s3://.../v3/")
    ^                                    ^
    |                                    |
EnvironmentDatasetRequest(dev, current_version_id=<v3>)
EnvironmentDatasetRequest(qa,  current_version_id=<v3>)
EnvironmentDatasetRequest(sit, current_version_id=<v3>)
```

`DatasetVersion.referenced_by_environments` (computed at read time from
every `EnvironmentDatasetRequest` currently pointing at it, never
stored) is how the API surfaces this — see the real walkthrough below,
Step 4.

## Try it yourself: a real, end-to-end run

`scripts/demo_phase7_lifecycle.py` runs the *real* Phase 6 certification
pipeline twice (against the `tiny` estate) to produce two real
`CertificationReport`s, then exercises every Phase 7 endpoint against
them through a real FastAPI `TestClient` (a genuine in-process ASGI
call, not a mock) backed by a real on-disk SQLite database:

```bash
python scripts/demo_phase7_lifecycle.py
```

Real output from exactly this command (abbreviated where repetitive):

```
STEP 1 -- Run the real Phase 6 certification pipeline (dataset version 1)
Status: PUBLISHED  Gates: 11/11 passed
Final artifact directory: ...\phase7-demo\run-v1\masked (79262 bytes on disk)
Row counts: {'address': 14, 'claim': 18, ..., 'provider': 10}

STEP 2 -- Register dataset version 1 via the real Phase 7 control-plane API
Registered version_id=2fc04a99-...  version_number=1

STEP 3 -- Request the dataset into DEV, QA, SIT, UAT, and PERFORMANCE
           dev: current_version=1  next_refresh_at=2026-10-02T17:44:01Z
            qa: current_version=1  next_refresh_at=2026-10-02T17:44:01Z
           sit: current_version=1  next_refresh_at=2026-10-09T17:44:01Z
           uat: current_version=1  next_refresh_at=None
   performance: current_version=1  next_refresh_at=2026-10-25T17:44:01Z

STEP 4 -- Confirm zero duplicate physical copies
DatasetVersion.storage_uri is referenced by: ['dev', 'qa', 'sit', 'uat', 'performance']
All 5 environments point at the SAME storage_uri: ...\phase7-demo\run-v1\masked

STEP 5 -- Refresh cadence computed per environment
           dev: cadence=weekly          next_refresh_at = requested_at + 7 days
            qa: cadence=weekly          next_refresh_at = requested_at + 7 days
           sit: cadence=biweekly        next_refresh_at = requested_at + 14 days
           uat: cadence=release_driven  next_refresh_at = None (no fixed schedule)
   performance: cadence=monthly         next_refresh_at = requested_at + 30 days

STEP 6 -- Run a second real certification pipeline run (dataset version 2)
Registered version_id=f47570e3-...  version_number=2

STEP 7 -- On-demand refresh: move DEV onto version 2
Refresh run: succeeded=True  detail=Refreshed to version 2
DEV now on version 2 (QA remains on version 1)

STEP 8 -- Roll DEV back to version 1
Rolled back DEV: from v2 -> v1
Version 2 status after rollback (unreferenced by any environment): rolled_back

STEP 9 -- Revoke version 1; confirm existing usage is undisturbed but new selection is blocked
Version 1 status: revoked
DEV's request is UNCHANGED (still points at revoked version 1)
A brand-new dataset with no ACTIVE version: 409
Attempting to roll QA back to the now-revoked version 1: HTTP 409

STEP 10 -- Orchestration abstraction: what needs refreshing right now
Due 400 days from now: 4 request(s) -> ['dev', 'qa', 'sit', 'performance']
(UAT never appears here -- release_driven has no fixed schedule.)
Scheduled sweep executed: 4 succeeded, 0 failed

DONE -- Phase 7 dataset lifecycle demo completed successfully
```

Every number above came from a real run — nothing in this file is
hand-typed sample output.

## Revocation: what happens to environments already using a revoked version

This is a deliberate design decision worth stating explicitly (Step 9
above demonstrates it): revoking a `DatasetVersion` **does not**
automatically move any `EnvironmentDatasetRequest` currently pointed at
it onto a different version. Two reasons:

1. **A silent forced migration is its own operational risk.** An
   environment mid-test-run having its data silently swapped out from
   under it (even to a "safer" version) can produce confusing,
   hard-to-reproduce failures of its own — arguably worse than staying
   on a known-revoked version for a bounded time.
2. **Visibility, not automation, is the correct first response.** The
   revoked status is immediately visible in
   `GET /dataset-versions/{id}` and in every affected
   `EnvironmentDatasetRequest`'s resolved version; an operator decides
   the next action (typically an explicit rollback to a different
   version, or an on-demand refresh once a fixed version is available)
   with full context, rather than the platform guessing on their
   behalf.

What revocation *does* enforce, immediately and by code (not
convention): `request_environment`, `refresh`, and `rollback` all
refuse to newly *select* a `REVOKED` version going forward (see Step 9's
409 responses above).

## The orchestration abstraction

`control_plane.domain.lifecycle.scheduler.RefreshOrchestrator` is a
two-method `ABC` (`due_refreshes`, `run_due_refreshes`);
`LocalRefreshOrchestrator` is the one real, in-process implementation,
exposed as `GET /api/v1/lifecycle/scheduler/due` and
`POST /api/v1/lifecycle/scheduler/run-due`. See
[ADR-0012](../adr/0012-refresh-orchestration-abstraction.md) for the
full reasoning and the concrete walkthrough of how a future Airflow DAG
or Databricks Workflow would call the same two endpoints from inside its
own scheduled task — this phase deliberately does not fake an Airflow
integration, only builds and documents the real seam one would plug
into.

## The API surface

All under `/api/v1/lifecycle`:

| Method | Path | Purpose |
|---|---|---|
| POST | `/dataset-versions` | Register a new version from a `CERTIFIED`/`PUBLISHED` `CertificationReport` |
| GET | `/dataset-versions` | List versions, filterable by `dataset_name`/`status` |
| GET | `/dataset-versions/{id}` | Fetch one version |
| POST | `/dataset-versions/{id}/revoke` | Revoke a version |
| GET | `/refresh-policies` | List configured policies |
| GET | `/refresh-policies/{environment}/default` | The environment-wide default policy (seeded on first access) |
| PUT | `/refresh-policies` | Create/update a policy (bumps `policy_version`) |
| POST | `/environment-requests` | Request a dataset into an environment (idempotent) |
| GET | `/environment-requests` | List requests, filterable by `environment`/`dataset_name` |
| GET | `/environment-requests/{id}` | Fetch one request |
| POST | `/environment-requests/{id}/refresh` | Trigger a refresh (on-demand by default) |
| POST | `/environment-requests/{id}/rollback` | Roll an environment back to a prior version |
| GET | `/scheduler/due` | What needs refreshing right now |
| POST | `/scheduler/run-due` | Execute every currently-due scheduled refresh |

## What this phase does and does not cover

- Reuses Phase 6's real `CertificationReport` unmodified as the only
  valid input to `register_dataset_version` — this phase adds no new
  data-transformation logic, only lifecycle state and orchestration.
- Retention/expiry (`LifecycleRepository.apply_retention`) is a plain
  repository method a scheduler would call periodically, same as
  `RefreshOrchestrator.run_due_refreshes` — no cron/daemon process runs
  it automatically inside this repository (see `problems_phase_07.md`).
- Does **not** wire this API as a `JobType`-driven control-plane
  orchestrated job the way `ROADMAP.md` describes for a later
  orchestration phase — these are synchronous REST endpoints, not a job
  queue.
- Real PostgreSQL verification remains deferred, same honest pattern
  `problems_phase_01.md` P1-1 established — see `problems_phase_07.md`.
