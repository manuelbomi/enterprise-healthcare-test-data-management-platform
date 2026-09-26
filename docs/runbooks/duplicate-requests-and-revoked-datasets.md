# Runbook: duplicate refresh/registration requests, and a consumer requesting a revoked dataset

> **Status:** REAL procedure (Phase 11), backed by real, passing tests
> against real code. Two related but distinct operational scenarios are
> covered together because they share the same underlying principle:
> the platform is built to fail safely (reject cleanly, never
> silently duplicate or serve something unsafe) rather than require an
> operator to prevent the situation from occurring in the first place.

## Scenario A: a refresh or dataset-version registration was submitted twice

### Symptom

A client (a script, a CI job, a person double-clicking a button) called
`POST /api/v1/lifecycle/environment-requests/{id}/refresh` or
`POST /api/v1/lifecycle/dataset-versions` more than once for what was
logically the same operation — often because the first call's response
was lost (a network timeout, a proxy retry) and the caller cannot tell
whether it actually succeeded.

### Impact

None, by design — both endpoints are safe to call more than once:

- **Refresh**: each call produces its own `RefreshRunRecord` (a real,
  distinct execution is genuinely something that happened and is
  correctly logged as such), but never creates a duplicate
  `EnvironmentDatasetRequest` (enforced by a unique constraint on
  `(environment, dataset_name)`) and never creates a duplicate
  `DatasetVersion`.
  **Backing test**: `services/control-plane/tests/test_failure_injection.py::test_duplicate_refresh_requests_do_not_corrupt_state`.
- **Dataset-version registration**: calling it twice with the
  *identical* `CertificationReport` now returns the *same*
  `DatasetVersion` both times (Phase 11 fix — see
  `docs/problems/problems_phase_11.md`'s "Resolved problems" for the real duplicate-row
  bug this closed).
  **Backing test**: `...::test_duplicate_dataset_version_registration_is_idempotent`.

### Diagnosis

1. `GET /api/v1/lifecycle/environment-requests?dataset_name=<name>` —
   confirm exactly one request exists per `(environment, dataset_name)`.
2. `GET /api/v1/lifecycle/dataset-versions?dataset_name=<name>` —
   confirm no two versions share the same underlying
   `certification_report_id` (they cannot, post-fix, but this is the
   check to run if investigating an *old* duplicate from before this
   phase's fix was deployed).

### Resolution

Nothing to do for a genuinely duplicate call — it already resolved
safely. If investigating a pre-Phase-11 duplicate (two
`DatasetVersion`s for the same certification report, from before the
idempotency fix): the earlier-created version is authoritative (lower
`version_number`); the later, spurious duplicate should be revoked
(`POST /dataset-versions/{id}/revoke`, with a reason noting it was a
pre-fix duplicate) rather than deleted, preserving the audit trail.

### The one gap this does NOT close

`docs/problems/problems_phase_07.md` P7-2 (unchanged by this phase): two *concurrent*
calls to `POST /api/v1/lifecycle/scheduler/run-due` (the scheduler
sweep, as opposed to a single request's own `/refresh` endpoint) have
no distributed lock preventing an overlapping sweep. This runbook's
"safe to call twice" guarantee is about repeating *one* logical
operation, not about two scheduler processes racing each other — that
remains a real, open gap for whichever future phase stands up an
actual external scheduler deployment (per
[ADR-0012](../adr/0012-refresh-orchestration-abstraction.md)).

---

## Scenario B: a business consumer's request targets a dataset whose only version was revoked

### Symptom

A `ConsumerDatasetRequest`
(`POST /api/v1/governance/consumer-requests/{id}/fulfill`) fails with
HTTP 409, and investigation shows the dataset's only registered
`DatasetVersion` has `status: "revoked"`.

### Impact

- The consumer (e.g. `LEFT_ARM`/`RIGHT_ARM`) does not get a new
  environment provisioned against unsafe/defective data — this is the
  system working as intended, not a bug.
- If the consumer already had a *previously fulfilled* request pointing
  at a version that has since been revoked, that existing
  `EnvironmentDatasetRequest` is **left untouched** — Phase 7's
  deliberate, documented "visibility over automation" decision
  (`docs/tutorial/07-dataset-lifecycle-and-refresh.md`): revocation
  never silently migrates an environment already using a revoked
  version. The consumer keeps running against the revoked version
  until someone explicitly rolls it back or a new version is
  registered and the environment is refreshed onto it.

**Backing test**:
`services/control-plane/tests/test_failure_injection.py::test_consumer_cannot_fulfill_request_against_a_dataset_whose_only_version_is_revoked`
— proves this holds when reached through the *governance* layer's
`fulfill_consumer_request` (Phase 10's integration point), not only
through a direct Phase 7 API call.

### Diagnosis

1. `GET /api/v1/lifecycle/dataset-versions?dataset_name=<name>` — check
   every version's status. If every version is `revoked`/`expired`/
   `rolled_back`, no ACTIVE version exists for any new request/refresh
   to select.
2. `GET /api/v1/audit/events?subject=<version_id>` (Phase 11) — see
   exactly who revoked the version, when, and why (the `reason` field
   recorded at revocation time, now durably queryable rather than only
   visible in the moment).
3. Check whether the consumer's existing (already-fulfilled)
   environment request is still pointed at the revoked version:
   `GET /api/v1/lifecycle/environment-requests?dataset_name=<name>`.

### Resolution

1. **A replacement version must be registered** (a new certification
   pipeline run producing a `CERTIFIED`/`PUBLISHED` report, then
   `POST /api/v1/lifecycle/dataset-versions`) before any new consumer
   request for this dataset can be fulfilled.
2. Once registered, retry
   `POST /api/v1/governance/consumer-requests/{id}/fulfill` — it will
   resolve against the new ACTIVE version.
3. If a consumer's *existing* environment is still on the revoked
   version and needs to move off it, that requires an explicit refresh
   (`POST /api/v1/lifecycle/environment-requests/{id}/refresh`) after
   the replacement version exists — it will not happen automatically,
   by design (see Impact above).

### Prevention / follow-up

- This is the correct, safe behavior, not a defect to "fix" — the
  follow-up work is upstream: investigate *why* the version was
  revoked (a real masking/data defect, per the revocation reason) and
  ensure the next certification run actually addresses it before
  re-registering, rather than registering a replacement that repeats
  the same defect.
