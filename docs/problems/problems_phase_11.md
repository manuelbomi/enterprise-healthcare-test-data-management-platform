# Problems — Phase 11 (Platform Integrity)

Phase-specific problem log, per `CONTRIBUTING.md`'s per-phase process:
written before/during implementation, updated as work proceeded, resolved
entries removed once fixed and tested. Anything left below at the end of
the phase is a genuine open issue for a later phase.

## Scope note: what earlier phases already satisfy

`ROADMAP.md` Phase 11 asks for a long list of platform-integrity
controls. Several are already real, built in earlier phases -- this
phase does not reimplement them, only cross-references and (where a
genuine gap exists) extends them:

- **Certification validation / "FAILED must not be publishable"** --
  Phase 6 (`data_plane.certification.state_machine`,
  `docs/CERTIFICATION_VS_MASKING.md`). A real failure-injection test
  already exists there (a broken masking policy produces a `FAILED`
  report that cannot be published).
- **Tamper-evidence for a persisted artifact** -- Phase 6's HMAC
  signing (`data_plane.certification.signing`), including a real
  hand-edit-then-detect test.
- **Dataset rollback/revocation** -- Phase 7
  (`control_plane.domain.lifecycle.repository`), demonstrated end to
  end in `scripts/demo_phase7_lifecycle.py` including a blocked
  attempt to roll an unrelated environment onto a freshly revoked
  version (HTTP 409).
- **Consumer requests use only an approved policy version** -- Phase
  10 (`GovernanceRepository.submit_consumer_request`,
  `test_consumer_cannot_attach_custom_masking_rules`).
- **Secret resolution refuses to run with no key** -- Phase 3
  (`data_plane.masking.secrets.resolve_hmac_key`) and Phase 6
  (`data_plane.certification.signing.resolve_signing_key`), both with
  existing unit tests for the missing-key case.
- **Masking job idempotency** -- Phase 3 already has a real,
  pipeline-level idempotency test
  (`test_masking_is_idempotent_across_two_independent_runs`,
  `test_rerunning_the_engine_twice_is_idempotent_end_to_end`).
- **"No secrets committed" scanning** -- Phase 3
  (`test_no_secrets_committed.py`, `test_certification_no_secrets_committed.py`)
  already exists, scoped to the one secret each of those phases
  introduced.

This phase's job is the genuinely new cross-cutting work: readiness
(as distinct from liveness), RBAC as a real enforced mechanism (not a
no-op), audit logging wired to real mutations, retry-policy
documentation/implementation, a dead-letter concept, config
validation, a repo-wide secret-detection script (generalizing Phase
3's scoped test), a dependency-scanning hook (script only -- CI wiring
is Phase 12), and eight real failure-injection tests, extending the
above where a genuine gap was found.

## Risks identified before implementation

- **RBAC could easily become a no-op that always allows** (the
  explicit anti-pattern the phase brief calls out). Mitigated by
  building `control_plane.platform.rbac.authorize()` as a real
  permission-table lookup, enforced at the API layer *before* any
  repository mutation runs, with a real test proving a
  `REQUESTER`-role actor is rejected (HTTP 403) attempting to approve
  a policy version or revoke a dataset version -- the same shape of
  proof Phase 10's `test_consumer_cannot_attach_custom_masking_rules`
  used for its own "not just a no-op" claim.
- **Adding a required `actor_role` field to existing request bodies
  breaks every earlier phase's existing test/demo call sites for those
  two endpoints.** Resolved by scoping the new required field to only
  the highest-sensitivity mutations (dataset version revoke/rollback,
  policy version approve/reject) and updating every existing call site
  (tests in `test_lifecycle_repository.py`/`test_lifecycle_api.py`/
  `test_governance_repository.py`/`test_governance_api.py`, plus the
  Phase 7/10 demo scripts) rather than defaulting the field to an
  always-allowed role, which would have been the "fake RBAC" anti-pattern
  in a different disguise.
- **Writing an audit "access denied" event in the same DB session as
  the rejected mutation risks the denial record itself being rolled
  back** (since `control_plane.db.session.session_scope` rolls back on
  *any* exception, including the `HTTPException` raised after an
  authorization failure). Resolved by performing the RBAC check at the
  API layer *before* calling into the repository, and calling
  `session.commit()` explicitly right after recording the denial event
  and before raising `HTTPException` -- the denial write is durable
  even though the request as a whole still returns 403.
- **"Masking job crashes halfway" needed an honest answer, not a
  hand-wave.** Investigated directly against `data_plane.masking.dataset_masker`:
  confirmed a real gap (see "Resolved problems" below for the fix that
  was applied) -- several of the five per-source-system maskers write
  output files incrementally (e.g. `mask_clinical_data_lake` writes
  each masked NDJSON row as it goes) with no atomic write / completion
  marker, so a mid-run exception leaves a partially-written output
  directory that is indistinguishable on disk from a complete one.
- **Container health**: `infra/docker/` has no `Dockerfile` for any
  service yet (only `docker-compose.yml` referencing local
  Postgres/MinIO images, no application image build). Building a
  container just to add a `HEALTHCHECK` directive to it would be
  scope creep ahead of the phase that actually containerizes the
  services (Phase 12). This phase documents the *design intent*
  (`docs/PLATFORM_INTEGRITY.md`) against the real `/api/v1/health` and
  `/api/v1/ready` endpoints this phase adds, and leaves the gap open
  below rather than fabricating a Dockerfile that doesn't serve any
  other purpose yet.

## Open problems

### P11-1 — Masking's incremental per-file writes are not atomic; only the top-level completion marker is new

- **Status:** **resolved in Phase 18A.** Every per-source-system masker
  in `data_plane.masking.dataset_masker` (`mask_postgres_enrollment`,
  `mask_claims_parquet`, `mask_clinical_data_lake`, `mask_pbm_extract`,
  `mask_partner_lab_feed`) now writes to a temporary path in its own
  destination directory and atomically renames it into place
  (`_atomic_write_via`/`_atomic_text_writer`) only on clean completion
  -- the exact gap this entry's "what this does not fix" paragraph
  below described. Proven by
  `tests/masking/test_dataset_masker_atomic_writes.py`, including a real
  crash injected mid-write into `mask_clinical_data_lake` (the same
  writer this entry names) that leaves no truncated file at its final
  path, on both a first write and an overwrite of a previous good run.
  See `docs/problems/problems_final_review.md`'s (now-deleted) P1-6 for the
  production-readiness framing that prompted this fix. The description
  below is left as originally written, for the historical record of
  what this phase (11) did and did not close.
- **Status (original, Phase 11):** open (partially mitigated, not fully solved)
- **Description:** `data_plane.masking.dataset_masker.mask_estate` now
  writes a `_MASKING_RUN_INCOMPLETE.marker` file at the start of a run
  and removes it only on successful completion (this phase's fix --
  see `test_failure_injection.py::test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output`),
  so a downstream consumer/operator can now tell "did this masking run
  actually finish" without guessing. What this does **not** fix: an
  individual per-source-system masker (e.g.
  `mask_clinical_data_lake`, which writes NDJSON rows one at a time
  into an already-open file handle) can still leave a **truncated,
  individually-plausible-looking file** for the one source system that
  was mid-write when the crash happened -- the marker tells you the
  *run* is incomplete, but does not by itself tell you *which specific
  file* was truncated versus which of the earlier source systems
  finished cleanly.
- **Repro / detail:** See the new failure-injection test -- it
  monkeypatches `mask_clinical_data_lake` to raise partway through
  processing rows and confirms the marker survives (proving the
  run-level signal works), but does not assert anything about the
  byte-level completeness of the one partially-written NDJSON file
  itself.
- **Affected files:**
  `services/data-plane/src/data_plane/masking/dataset_masker.py`
- **Owner for resolution:** A future phase (or a Phase 11 follow-up)
  that changes each per-source-system masker to write to a temporary
  path and rename atomically on completion -- a larger, higher-risk
  refactor of code exercised by ~80 existing Phase 3 tests, deliberately
  not attempted in this phase to avoid destabilizing that suite for a
  partial improvement when the run-level marker already gives a real,
  testable safety signal.

### P11-2 — No real container image / `HEALTHCHECK` exists yet

- **Status:** open (documented design intent only, not fabricated)
- **Description:** `infra/docker/` has no `Dockerfile` for
  `control-plane`, `data-plane`, or `governance-service` -- only
  `docker-compose.yml` for local Postgres/MinIO. There is nothing to
  attach a container `HEALTHCHECK` directive to yet.
- **Repro / detail:** N/A -- no container exists.
- **Affected files:** `infra/docker/` (none yet)
- **Owner for resolution:** Phase 12 (CI/CD and cloud testing), which
  is the first phase that containerizes the services. This phase's
  `docs/PLATFORM_INTEGRITY.md` documents the exact `HEALTHCHECK`
  shape Phase 12 should use, pointing at this phase's real
  `/api/v1/health` (liveness) and `/api/v1/ready` (readiness)
  endpoints so Phase 12 does not have to re-derive the design.

### P11-3 — Dependency-scanning hook is a real script, not yet wired into CI

- **Status:** open (deliberately scoped -- CI itself is Phase 12)
- **Description:** `scripts/security/dependency_scan.py` is a real,
  runnable script (uses `pip-audit` if available on `PATH`, and fails
  loudly/honestly rather than silently passing if it is not, since a
  scan that silently no-ops is worse than no scan) but nothing in
  `.github/workflows/ci.yml` calls it yet.
- **Repro / detail:** Run `python scripts/security/dependency_scan.py`
  directly; it works standalone. `.github/workflows/ci.yml` is
  untouched by this phase.
- **Affected files:** `scripts/security/dependency_scan.py`,
  `.github/workflows/ci.yml` (not modified)
- **Owner for resolution:** Phase 12, the same owner
  `docs/adr/0012-refresh-orchestration-abstraction.md` names for
  wiring a real external trigger into a seam this repository already
  built for it.

### P11-4 — RBAC is enforced only on the four highest-sensitivity mutations, not every lifecycle/governance endpoint

- **Status:** open (scoped, not a full RBAC rollout)
- **Description:** `control_plane.platform.rbac.authorize()` is real
  and enforced (not a no-op) on dataset-version revoke, environment
  rollback, and policy-version approve/reject. Every other
  `/api/v1/lifecycle/*` and `/api/v1/governance/*` mutation (register a
  dataset version, request/refresh an environment, draft/submit a
  policy version, register a business consumer, submit/fulfill a
  consumer request) still has no RBAC check, same gap
  `docs/problems/problems_phase_07.md` P7-6 and `docs/problems/problems_phase_10.md` P10-2
  originally documented for their *own* endpoints -- this phase
  narrows, but does not close, those two entries (see the updated text
  in those files).
- **Repro / detail:** `POST /api/v1/lifecycle/environment-requests`
  succeeds with no `actor_role` field at all.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/lifecycle.py`,
  `services/control-plane/src/control_plane/api/v1/governance.py`
- **Owner for resolution:** `services/governance-service`, once built
  out for real, per `ARCHITECTURE.md` section 2.4 -- same eventual
  owner P7-6/P10-2 already named.

### P11-5 — Audit log is a real, append-only DB table, but not yet the security/governance plane's own store

- **Status:** open (documented scope boundary)
- **Description:** `control_plane.platform.audit.AuditLogRepository`
  writes to a real table (`audit_event`) in the *same*
  `control_plane.db.models` schema/engine every other Phase 7/10 table
  lives in -- not the dedicated, separately-deployable
  `services/governance-service` `ARCHITECTURE.md` section 2.4 describes
  as the audit log's eventual home. This mirrors exactly the same,
  already-accepted tradeoff ADR-0014 documents for masking governance
  living in `services/control-plane` rather than
  `services/governance-service` (a same-transaction integration with
  Phase 7/10's existing schema was the deciding factor here too --
  the RBAC-denial write and the rejected mutation must be
  observable/consistent within one request).
- **Repro / detail:** N/A -- design clarification.
- **Affected files:** `services/control-plane/src/control_plane/platform/audit.py`,
  `services/control-plane/src/control_plane/db/models.py`
- **Owner for resolution:** `services/governance-service`, once built
  out for real; Phase 13 ("Auditability and compliance evidence") is
  the next phase in `ROADMAP.md` that touches this area directly.

### P11-6 — Retry policy is implemented for one real call site (readiness DB check), not for job execution stages

- **Status:** open (documented scope boundary, consistent with the
  phase's own honesty requirement)
- **Description:** `control_plane.platform.retry.retry_with_backoff`
  is a real, tested, generic retry helper, wired into the `/api/v1/ready`
  endpoint's database connectivity check (a legitimately retryable
  transient failure). It is deliberately **not** wired into
  masking/subsetting/certification job execution -- per this phase's
  own "masking job crashes halfway" finding (P11-1), blindly retrying
  a job that already wrote partial output onto the same path would
  make the corruption risk *worse*, not better, until P11-1's
  atomic-write gap is closed. `docs/PLATFORM_INTEGRITY.md` documents
  this reasoning explicitly (retry is safe for read-only/idempotent
  operations like a DB health check; it is not safe, yet, for a
  data-plane job with non-atomic partial writes).
- **Repro / detail:** N/A -- design clarification.
- **Affected files:** `services/control-plane/src/control_plane/platform/retry.py`
- **Owner for resolution:** The same future phase/follow-up that
  closes P11-1 (atomic per-file writes) should revisit whether job-level
  retry becomes safe to add at that point.

## Resolved problems

- **Duplicate dataset-version registration created two `DatasetVersionRow`s
  for the same `CertificationReport`.** Found while writing this
  phase's "job idempotency" test: calling
  `LifecycleRepository.register_dataset_version` twice with the
  identical `CertificationReport` (e.g. a client retrying after an
  ambiguous network timeout) created two distinct, differently-numbered
  `DatasetVersionRow`s pointing at the same `storage_uri`. Fixed:
  `register_dataset_version` now checks for an existing row with the
  same `certification_report_id` first and returns it unchanged if
  found, mirroring the exact idempotency convention
  `request_environment` already documented for itself. Covered by
  `test_failure_injection.py::test_duplicate_dataset_version_registration_is_idempotent`.
- **Masking's `mask_estate` gave no on-disk signal that a run crashed
  partway through.** Fixed with a minimal, additive completion marker
  (`_MASKING_RUN_INCOMPLETE.marker`, written at the start of
  `mask_estate`, removed only on clean completion) -- see P11-1 above
  for what this does and does not fully solve.
