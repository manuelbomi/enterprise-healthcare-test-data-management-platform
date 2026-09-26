# Problems — Phase 7 (Dataset Lifecycle and Refresh Management)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before implementation began (this initial version), updated as
work proceeded, resolved entries removed once fixed and tested. Anything
left below at the end of the phase is a genuine open issue for a later
phase.

## Risks identified before/during implementation, and how they were resolved

- **"Avoid unnecessary duplicate physical copies" needed a real
  mechanism, not just a claim.** Resolved architecturally:
  `DatasetVersion` is environment-agnostic (no `target_environment`
  field), and every `EnvironmentDatasetRequest` (one per
  `(environment, dataset_name)`) references a `DatasetVersion` by
  foreign key (`current_version_id`), never by copying `storage_uri`.
  Verified end to end by a real run
  (`scripts/demo_phase7_lifecycle.py`, Step 4): five environments
  requesting the same dataset all resolve to the exact same
  `storage_uri`, and `DatasetVersion.referenced_by_environments`
  (computed at read time from live foreign-key references, never
  stored/denormalized) shows all five. See
  `docs/adr/0012-refresh-orchestration-abstraction.md`'s sibling
  reasoning and `docs/tutorial/07-dataset-lifecycle-and-refresh.md`.
- **Revocation needed a real, defensible answer to "what happens to
  environments already using the revoked version," not a hand-wave.**
  Decided and implemented: revocation is forward-looking only.
  `revoke_version` never touches any `EnvironmentDatasetRequestRow`; it
  only transitions the `DatasetVersionRow`'s own status (via the
  enforced `state_machine.transition`) and is independently checked by
  `request_environment`, `refresh`, and `rollback` before they will
  select that version going forward. Verified by
  `test_revoke_does_not_move_an_environment_already_using_it` and the
  demo script's Step 9 (a 409 on the attempt to roll an unrelated
  environment back onto a freshly revoked version, while the
  environment already on it is provably untouched).
- **"Rolled back" needed to be a real, queryable `DatasetVersionStatus`
  value (per `ROADMAP.md`'s explicit "active/expired/revoked/
  rolled-back" list), but a dataset version can be shared by multiple
  environments, so one environment's rollback cannot simply flip a
  shared row's status.** Resolved by scoping the transition to
  "no environment references this version anymore *and* the reason it
  stopped being referenced was an explicit rollback, not an ordinary
  forward refresh": `rollback()` only transitions the FROM version
  ACTIVE -> ROLLED_BACK if, after moving the one environment's pointer,
  zero `EnvironmentDatasetRequestRow`s still reference it. A version
  shared with another environment that is *not* rolling back stays
  ACTIVE. Verified by
  `test_rollback_sharing_from_version_with_another_environment_does_not_change_its_status`.
- **Plane separation (ADR-0003) needed to stay real for this phase's
  end-to-end demonstration, which genuinely needs a real Phase 6
  `CertificationReport` as input.** `services/control-plane`'s own
  source (and its own test suite, via `conftest.py`'s hand-authored
  `make_certified_report`) never imports `data_plane`, exactly like
  Phase 2-6 before it. The one place both packages are imported
  together is `scripts/demo_phase7_lifecycle.py`, a standalone operator
  script outside either service's installed package -- the same shape
  a real CI job gluing a certification CLI run to a control-plane API
  call would take. See that script's module docstring for the full
  reasoning.

## Open problems

### P7-1 — Real PostgreSQL verification remains deferred

- **Status:** open (deliberately deferred; same honest pattern
  `docs/problems/problems_phase_01.md` P1-1 established)
- **Description:** `control_plane.db.models` avoids Postgres-only
  column types (no `JSONB`, no native `UUID`) specifically so the schema
  is portable, and `create_postgres_engine`/`Settings.lifecycle_database_url`
  accept a real `postgresql+psycopg://...` DSN unmodified. No real
  PostgreSQL instance has actually been started against this schema in
  this environment (`infra/docker-compose` is not running here) --
  every test and the demo script use local SQLite.
- **Repro / detail:** Start `infra/docker-compose`'s Postgres service,
  set `TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL=postgresql+psycopg://...`,
  and rerun `services/control-plane/tests/test_lifecycle_repository.py`
  and `test_lifecycle_api.py`. Expected: passes unmodified (no
  SQLite-specific behavior is relied upon anywhere in
  `control_plane.domain.lifecycle`/`control_plane.db.models`).
- **Affected files:** `services/control-plane/src/control_plane/db/models.py`,
  `services/control-plane/src/control_plane/config.py`
- **Owner for resolution:** Not currently scheduled by name; same
  owner-note pattern as P0-3/P1-1 (infra stand-up is a later phase's
  concern).

### P7-2 — No distributed-lock / exactly-once guarantee for concurrent scheduler sweeps

- **Status:** open (documented limitation, not a defect; explicitly
  scoped out in ADR-0012)
- **Description:** If two callers invoke
  `POST /api/v1/lifecycle/scheduler/run-due` (or two
  `LocalRefreshOrchestrator.run_due_refreshes` calls) concurrently
  against the same database, both could observe the same request as
  "due" and both attempt to refresh it. SQLite (used everywhere in this
  phase's tests) serializes writes at the file level, so this cannot
  actually corrupt data locally, but there is no application-level lock
  preventing a duplicate `RefreshRunRow` from being written for the same
  logical refresh. A real production deployment would rely on the
  scheduler itself (e.g. Airflow's single-active-DAG-run semantics, or
  a Kubernetes CronJob's `concurrencyPolicy: Forbid`) to prevent
  overlapping sweeps -- this repository does not implement that itself.
- **Repro / detail:** Call `run-due` twice in rapid succession against a
  request whose `next_refresh_at` is in the past; both calls can succeed
  and both write a `RefreshRunRow`, though only the second write's
  `current_version_id` result persists (last write wins).
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/scheduler.py`,
  `services/control-plane/src/control_plane/domain/lifecycle/repository.py`
- **Owner for resolution:** A future phase that stands up a real
  scheduler deployment (Airflow/Databricks Workflows/a cloud scheduler),
  per ADR-0012.

### P7-3 — Retention/expiry sweep (`apply_retention`) has no automatic trigger

- **Status:** open (documented limitation, not a defect)
- **Description:** `LifecycleRepository.apply_retention(as_of=...)` is a
  real, tested method that expires ACTIVE versions past their
  `expires_at`, but nothing calls it automatically -- there is no daemon,
  cron entry, or API endpoint that runs it on a schedule inside this
  repository. It must be invoked explicitly (by a script, a test, or a
  future scheduled task using the same `RefreshOrchestrator` seam
  ADR-0012 documents).
- **Repro / detail:** Register a version with a short `retention_days`,
  wait past `expires_at`, and observe `GET /dataset-versions` still
  shows it as `active` until `apply_retention` (or an equivalent future
  API endpoint) is explicitly called.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`
- **Owner for resolution:** Same scheduler-deployment phase as P7-2; a
  natural companion task to the refresh sweep.

### P7-4 — Retention is a per-dataset-version parameter, not automatically derived from an environment's `RefreshPolicy.retention_days`

- **Status:** open (documented design simplification, not a defect)
- **Description:** `RefreshPolicy.retention_days` exists and is
  configurable per environment (and optionally per dataset), but
  `register_dataset_version`'s own `retention_days` argument (default
  90) is a caller-supplied value independent of any environment's
  policy -- a `DatasetVersion` is environment-agnostic by design (see
  the "core design decision" in
  `docs/tutorial/07-dataset-lifecycle-and-refresh.md`), so there is no
  single environment's policy that could unambiguously set it when
  multiple environments with different retention policies might
  reference the same version. The caller (a real registration
  pipeline/CI job) is responsible for choosing a sensible
  `retention_days` today, typically the longest retention among the
  environments it expects to serve.
- **Repro / detail:** N/A -- design clarification. Changing a
  `RefreshPolicy.retention_days` after a version is already registered
  has no effect on that version's `expires_at`.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`
- **Owner for resolution:** Not currently scheduled by name; would need
  a policy-resolution design decision (e.g. "max retention across all
  environments currently requesting this dataset") beyond this phase's
  scope.

### P7-5 — `RefreshPolicy.grace_period_days` is stored and returned but not yet consumed by any "overdue" query

- **Status:** open (documented gap, not a defect)
- **Description:** The field exists in the contract and schema and can
  be set via `PUT /refresh-policies`, but no endpoint currently
  distinguishes "due" (`next_refresh_at <= as_of`, what
  `/scheduler/due` reports) from "overdue by more than its grace
  period" (`next_refresh_at + grace_period_days <= as_of`) -- the latter
  would be a useful alerting signal (e.g. "DEV hasn't refreshed in over
  a week past its due date") that isn't implemented yet.
- **Repro / detail:** N/A -- feature gap, not incorrect behavior.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`,
  `services/control-plane/src/control_plane/api/v1/lifecycle.py`
- **Owner for resolution:** Not currently scheduled by name; natural
  fit alongside P7-2/P7-3's scheduler-deployment work.

### P7-6 — No RBAC/authorization or audit-log integration on any lifecycle endpoint

- **Status:** **partially resolved in Phase 11** -- narrowed, not
  closed. `control_plane.platform.rbac.authorize()` now real, enforced
  RBAC gates `POST /dataset-versions/{id}/revoke` and
  `POST /environment-requests/{id}/rollback` (only
  `COMPLIANCE_APPROVER`/`PLATFORM_ADMIN` and `DATA_STEWARD`/
  `PLATFORM_ADMIN` respectively may call them; a real 403 for anyone
  else, proven by `test_failure_injection.py::test_insufficiently_privileged_actor_is_rejected_revoking_a_dataset_version`).
  `control_plane.platform.audit.AuditLogRepository` now writes a real,
  append-only `AuditEvent` for every lifecycle mutation this router
  performs (registration, revocation, environment request creation,
  refresh, rollback), queryable at `GET /api/v1/audit/events`. See
  [ADR-0015](docs/adr/0015-platform-integrity-controls-in-control-plane.md)
  and `docs/PLATFORM_INTEGRITY.md`.
- **Description (what remains open):** Every *other*
  `/api/v1/lifecycle/*` mutation (register a dataset version,
  request/refresh an environment) still performs no RBAC check at all
  -- only revoke/rollback are gated. `requested_by`, `performed_by`,
  `revoked_by`, `triggered_by`, and `created_by` remain caller-supplied
  free-text identity strings, not verified against a real identity
  provider -- `control_plane.platform.rbac` answers "if you claim this
  role, are you allowed to do this," not "are you who you claim to
  be." The audit log itself lives in `services/control-plane`'s own
  schema, not yet `services/governance-service`'s eventual dedicated
  store (see `docs/problems/problems_phase_11.md` P11-5).
- **Repro / detail:** `POST /api/v1/lifecycle/environment-requests`
  still succeeds with no `actor_role` field of any kind.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/lifecycle.py`,
  `services/control-plane/src/control_plane/platform/rbac.py`,
  `services/control-plane/src/control_plane/platform/audit.py`
- **Owner for resolution:** `services/governance-service`, once built
  out for real (full identity verification, RBAC over every remaining
  endpoint); see also Phase 13 (auditability and compliance evidence)
  for the audit log's eventual dedicated home.

### P7-7 — Lifecycle endpoints are synchronous REST calls, not `JobType`-driven orchestrated jobs

- **Status:** open (documented scope boundary, not a defect)
- **Description:** `healthcare_tdm_contracts.JobType` (Phase 0 scaffold)
  still has no `LIFECYCLE_REFRESH`/`DATASET_REGISTRATION` member, and
  nothing in this phase submits a `JobRequest`/consumes a `JobResult`
  for a refresh or registration -- every Phase 7 operation is a
  synchronous FastAPI request/response, same shape of gap
  `docs/problems/problems_phase_03.md` P3-1, `docs/problems/problems_phase_04.md` P4-1, and
  `docs/problems/problems_phase_06.md` P6-1 document for their own phases' outputs.
- **Repro / detail:** N/A -- scope boundary, not a bug.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/lifecycle.py`,
  `libs/contracts/src/healthcare_tdm_contracts/jobs.py`
- **Owner for resolution:** a future job-orchestration phase, same owner
  note as P6-1. **Correction:** this used to say "Phase 14 (job
  orchestration)" — Phase 14 actually happened and its scope was
  scale/performance benchmark tooling, not job-orchestration wiring; see
  `docs/problems/problems_phase_14.md`.

### P7-8 — `size_bytes` and `row_counts` are caller-supplied at registration, not independently re-derived by the control plane

- **Status:** open (documented limitation, not a defect)
- **Description:** `register_dataset_version` trusts the `size_bytes`
  and `row_counts` values the caller passes (typically computed by
  scanning the certification pipeline's output directory, as
  `scripts/demo_phase7_lifecycle.py` does) rather than independently
  re-deriving them by reading `storage_uri` itself. This mirrors the
  Phase 6 certification gates' own principle ("never trust an earlier
  stage's self-report without re-deriving it") being *not yet applied*
  here -- a caller could register incorrect metadata and the control
  plane would not catch it.
- **Repro / detail:** Register a version with `size_bytes=0` for a
  non-empty `storage_uri`; no validation rejects the mismatch.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`
- **Owner for resolution:** Not currently scheduled by name; would
  require the control plane to have direct read access to the object
  storage layer, which is Phase 8's territory (storage/compute
  footprint management).

## Resolved problems

_(None yet — this is the initial version of this file, written before
implementation. This section will list problems that were opened and
then resolved during this phase, kept briefly for history before being
pruned per `CONTRIBUTING.md` step 6, if any are found and fixed before
the phase is considered done.)_
