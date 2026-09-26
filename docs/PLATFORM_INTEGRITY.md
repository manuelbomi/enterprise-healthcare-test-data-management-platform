# Platform Integrity (Phase 11)

An honest account of every platform-integrity control `ROADMAP.md`
Phase 11 asks for: which ones already existed (with the earlier
phase's own name and test), which ones are genuinely new here, and
which ones remain real, documented gaps. Written in the same spirit as
`docs/CERTIFICATION_VS_MASKING.md` and `docs/CAPACITY_COST_TRADEOFFS.md`
— distinguishing real, measured/enforced behavior from illustrative or
partial coverage, rather than claiming full coverage for a portfolio
checklist.

## 1. Health checks / readiness / liveness

| Control | Status | Where |
|---|---|---|
| Liveness (`/api/v1/health`) | Already real (Phase 0) | `control_plane/api/v1/health.py` |
| Readiness (`/api/v1/ready`), dependency-aware | **New (Phase 11)** | `control_plane/platform/readiness.py`, `control_plane/api/v1/health.py` |

Liveness answers "is the process up." Readiness answers "can this
process serve real traffic right now" — it checks the lifecycle
database is actually reachable (`SELECT 1`, with retry via
`control_plane.platform.retry`) and reports (informationally, never
gating) whether the Phase 2 catalog artifact is present. Conflating
the two into one endpoint would mean a transient DB blip causes an
orchestrator to kill and restart an otherwise-healthy process instead
of just pausing traffic to it. See `control_plane/platform/readiness.py`'s
module docstring for the full reasoning.

## 2. Transaction boundaries

Already real, unchanged by this phase:
`control_plane.db.session.session_scope` is the one place a
`sqlalchemy.orm.Session` is opened, committed, or rolled back
(commit on clean exit, rollback on any exception). Every repository
(`LifecycleRepository`, `GovernanceRepository`, and this phase's
`AuditLogRepository`/`DeadLetterStore`) takes a `Session` it does not
own and never calls `commit()`/`rollback()` itself — with exactly one
documented exception this phase adds: an RBAC-denial audit event calls
`session.commit()` immediately so the denial record survives the
`HTTPException` raised right after it. See
[ADR-0015](adr/0015-platform-integrity-controls-in-control-plane.md)
for why.

## 3. Job idempotency

| Job / call | Idempotent? | Evidence |
|---|---|---|
| Masking (`mask_estate`, full pipeline, two independent runs) | Yes — already tested | Phase 3: `test_masking_is_idempotent_across_two_independent_runs`, `test_rerunning_the_engine_twice_is_idempotent_end_to_end` |
| `LifecycleRepository.request_environment` | Yes — already documented/tested | Phase 7: idempotent per `(environment, dataset_name)` |
| `LifecycleRepository.refresh` (called twice) | Yes — safe, not corrupting (two real, distinct log entries) | **New test (Phase 11)**: `test_duplicate_refresh_requests_do_not_corrupt_state` |
| `LifecycleRepository.register_dataset_version` (called twice with the identical report) | **Was NOT idempotent — real bug found and fixed this phase** | `test_duplicate_dataset_version_registration_is_idempotent`; see `docs/problems/problems_phase_11.md`'s "Resolved problems" |

The one genuine gap this phase found and fixed: a caller retrying
`register_dataset_version` after an ambiguous failure (e.g. a network
timeout where the first call actually succeeded server-side) used to
create two distinct `DatasetVersionRow`s pointing at the same
`storage_uri`. Fixed by checking for an existing row with the same
`certification_report_id` first.

## 4. Retry policies

**New (Phase 11)**: `control_plane.platform.retry.retry_with_backoff` —
a small, generic, tested retry-with-exponential-backoff helper.
Deliberately wired into exactly one real call site: the `/api/v1/ready`
database connectivity check (a read-only, side-effect-free operation
where retrying a transient failure is safe and helpful).

**Deliberately not** wired into data-plane job execution
(masking/subsetting/certification). Reasoning: this phase's own
"masking job crashes halfway" failure-injection test found that a
mid-run crash can leave a partially-written output directory with no
atomicity guarantee (see section 6 below). Blindly retrying a job
against the same output path in that state risks making corruption
*worse* (a second run's writes interleaving with the first run's
partial ones), not safer, until that gap is closed. See
`docs/problems/problems_phase_11.md` P11-6.

## 5. Dead-letter handling

**New (Phase 11)**: `control_plane.platform.dead_letter.DeadLetterStore`,
a durable, queryable, DB-backed record of individually-isolated
job/sweep failures. Wired into the one place this codebase already
isolates one item's failure from a batch —
`LocalRefreshOrchestrator.run_due_refreshes` (per
[ADR-0012](adr/0012-refresh-orchestration-abstraction.md)'s "isolate
one request's failure from the others" principle) — so a failed
scheduled refresh is now recorded durably, not only returned to the
one synchronous caller of that one sweep
(`RefreshSweepResult.errors`, which disappears the moment the HTTP
response is sent). See `test_scheduler_sweep_wires_a_real_failure_into_the_dead_letter_store`.

## 6. Schema validation / data-integrity checks

Already substantially real from Phase 6 (`data_plane.certification.gates`
— eleven independent gates, `check_schema_validation`,
`check_row_count_reconciliation`, `check_orphan_detection`, etc.). This
phase's new contribution is at the *filesystem* layer, one level below
those gates:

- **New**: `mask_estate`'s completion marker
  (`_MASKING_RUN_INCOMPLETE.marker`, `data_plane.masking.dataset_masker`)
  — see section 8 below.
- **New**: `test_corrupted_masked_parquet_is_rejected_downstream_not_silently_misread`
  proves that genuine byte-level file corruption (a real truncated
  Parquet file, not a mocked read error) is rejected by both
  `pandas.read_parquet` and the higher-level
  `data_plane.subsetting.estate_io.read_estate` — a corrupted dataset
  cannot be silently misread as a small-but-valid one.

## 7. RBAC

**New (Phase 11), and genuinely enforced, not a no-op**:
`control_plane.platform.rbac` — see
[ADR-0015](adr/0015-platform-integrity-controls-in-control-plane.md)
for the full design and `docs/problems/problems_phase_11.md` P11-4 for its honest,
narrow scope (four endpoints: dataset-version revoke/rollback,
policy-version approve/reject). `docs/problems/problems_phase_07.md` P7-6 and
`docs/problems/problems_phase_10.md` P10-2 are updated to reflect this partial
resolution.

## 8. Audit logging

**New (Phase 11)**: `control_plane.platform.audit.AuditLogRepository`,
the first real wiring of the Phase 0 `healthcare_tdm_contracts.AuditEvent`
contract to a durable, append-only store (`audit_event` table, same
schema/engine every other Phase 7/10 table lives in). Wired into every
real lifecycle/governance mutation this phase touches: dataset version
registration/revocation, environment requests/refreshes, environment
rollback, policy version approval/rejection, consumer request
submission/fulfillment, and RBAC denials themselves. Read via
`GET /api/v1/audit/events` (filterable by `event_type`/`subject`/`actor`,
no write endpoint exists). See `docs/problems/problems_phase_11.md` P11-5 for the
honest scope boundary (this is not yet `services/governance-service`'s
own store).

## 9. Configuration validation

**New (Phase 11)**: `control_plane.config.Settings` gained real
`field_validator`s — `log_level` must be a recognized Python logging
level, `api_v1_prefix` must start with `/`, `database_url`/
`lifecycle_database_url` must look like a real SQLAlchemy URL, and
every configured CORS origin must have a scheme. See
`test_config_validation.py`.

## 10. Secret detection

Already real and automated for the two specific secrets this
repository defines (`services/data-plane/tests/masking/test_no_secrets_committed.py`,
Phase 3; `test_certification_no_secrets_committed.py`, Phase 6).

**New (Phase 11)**: `scripts/security/detect_secrets.py` generalizes
this into a repo-wide scan (bare 64-hex-char strings, AWS access key
IDs, PEM private key headers, both known secret-shaped env vars, and a
conservative generic `password/secret/api_key/token = "..."` pattern),
runnable standalone today and intended for a future pre-commit
hook/CI step (Phase 12). Verified clean against this repository's
actual current tracked tree
(`test_running_against_the_real_tracked_repository_tree_is_clean`).

## 11. Dependency scanning hooks

**New (Phase 11)**: `scripts/security/dependency_scan.py` — runs
`pip-audit` against every workspace package if installed; reports an
explicit, non-zero failure (never a silent pass) if `pip-audit` is
unavailable. Not yet wired into CI — that is Phase 12's job (see
`docs/problems/problems_phase_11.md` P11-3). In this environment, `pip-audit` is not
installed, so running the script today correctly reports failure —
this is documented honestly rather than worked around.

## 12. Container health

**Not built** — `infra/docker/` has no `Dockerfile` for any service
yet (only `docker-compose.yml` for local Postgres/MinIO), so there is
no container to attach a `HEALTHCHECK` directive to. Documenting the
design intent here rather than fabricating a Dockerfile that would
serve no other purpose yet:

```dockerfile
# Illustrative -- for Phase 12, once a real Dockerfile exists for
# services/control-plane:
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -f http://localhost:8000/api/v1/health || exit 1
```

A container orchestrator (Kubernetes) would use the **liveness**
endpoint (`/api/v1/health`) for its `livenessProbe` (restart on
failure) and the **readiness** endpoint (`/api/v1/ready`) for its
`readinessProbe` (pull traffic, do not restart) — exactly the split
this phase's `control_plane/platform/readiness.py` module docstring
explains. See `docs/problems/problems_phase_11.md` P11-2.

## 13. Backup / restore

See `docs/runbooks/backup-and-restore.md` (new, Phase 11).

## 14. Failure recovery / dataset rollback / revocation

Already real from Phase 7 (`docs/runbooks/snapshot-refresh-failure.md`,
`docs/tutorial/07-dataset-lifecycle-and-refresh.md`). This phase adds
governance-layer proof (`test_consumer_cannot_fulfill_request_against_a_dataset_whose_only_version_is_revoked`)
and two new runbooks with real, tested recovery procedures — see
`docs/runbooks/README.md`'s updated index.

## 15. The eight failure-injection scenarios, at a glance

| # | Scenario | New/extended? | Test |
|---|---|---|---|
| 1 | Masking job crashes halfway | New test; real gap found + fixed (completion marker) | `services/data-plane/tests/platform_integrity/test_failure_injection.py::test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output` |
| 2 | Source schema changes | Extends Phase 2/6's existing drift handling with a new, direct proof of the masking-time safe fallback | `...::test_a_column_not_in_the_catalog_falls_back_to_safe_masking_not_raw_passthrough` |
| 3 | Storage unavailable | New | `...::test_storage_unavailable_fails_cleanly_without_a_leaked_stack_trace_of_raw_data` |
| 4 | Duplicate refresh request | New; extends Phase 7 | `services/control-plane/tests/test_failure_injection.py::test_duplicate_refresh_requests_do_not_corrupt_state`, `::test_duplicate_dataset_version_registration_is_idempotent` |
| 5 | Certification validation fails | Already real (Phase 6); this phase adds a control-plane-layer defense-in-depth extension | `...::test_a_failed_certification_report_cannot_be_registered_as_a_dataset_version` |
| 6 | Secret missing | Already unit-tested (Phase 3/6); this phase adds an integration-level proof | `services/data-plane/tests/platform_integrity/test_failure_injection.py::test_masking_with_no_key_anywhere_fails_fast_before_any_output_is_written` |
| 7 | Dataset becomes corrupted | New | `...::test_corrupted_masked_parquet_is_rejected_downstream_not_silently_misread` |
| 8 | Consumer requests revoked dataset | Already real (Phase 7); this phase adds the governance-layer angle | `services/control-plane/tests/test_failure_injection.py::test_consumer_cannot_fulfill_request_against_a_dataset_whose_only_version_is_revoked` |
