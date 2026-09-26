# Phase 17 — Principal-Engineer Production Readiness Review

**Scope:** review only. No application code, infrastructure, or documentation
other than this file was changed while producing it. Per the Phase 17 brief:
*"Do not fix anything yet. STOP."* Nothing below has been fixed — this is the
input Phase 18A/18B will fix or delete from.

**Method.** Before writing a single finding, this review read: `ARCHITECTURE.md`,
all 17 ADRs, every `docs/problems/problems_phase_01.md`-`docs/problems/problems_phase_15.md` (there is no
`docs/problems/problems_phase_16.md` — `ROADMAP.md`'s own Phase 16 section explains why, and
that explanation was verified rather than assumed), `docs/problems/problems_master.md`,
`docs/PLATFORM_INTEGRITY.md`, `docs/CERTIFICATION_VS_MASKING.md`,
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`, `docs/CAPACITY_COST_TRADEOFFS.md`,
`docs/COMPLIANCE_EVIDENCE.md`, `docs/SCALE_AND_PERFORMANCE.md`,
`docs/AZURE_PRODUCTION_DEPLOYMENT.md`, all four `docs/interview/*.md`,
`docs/runbooks/*.md`, `SECURITY.md`, `THREAT_MODEL.md`, `DATA_GOVERNANCE.md`,
`CONTRIBUTING.md`, `README.md`. Then, rather than trusting that prior art,
every category the brief lists was independently re-inspected against the
current source tree: every FastAPI router file in
`services/control-plane/src/control_plane/api/v1/`, the RBAC permission
table, the control-plane DB schema/engine setup, the masking/certification
secret-resolution code, the certification gate implementations, the entire
`frontend/src` tree (pages, API client, types, E2E specs), all three
Dockerfiles, the Helm chart templates and `values.yaml`, both Terraform
examples, `docker-compose.yml`, `.github/workflows/*.yml`, and a repo-wide
grep for logging/metrics/tracing infrastructure. The full four-package
pytest suite and the frontend Vitest/lint suite were actually executed (not
assumed) as evidence-gathering; results are in section "Test suite: real
results" below.

**Findings are classified P0-P3** per this document's own definition (see
"How severity was assigned" at the end). For every finding already named in
an existing `problems_phase_NN.md`/`docs/problems/problems_master.md` entry, that entry is
cited rather than re-derived from scratch — but the severity classification
below is this review's own, independent judgment, not an import of whatever
urgency language (if any) the original phase used. Findings not cited to any
existing entry were newly discovered during this review's own re-inspection.

---

## Phase 18A resolution note

**All ten P0/P1 findings below (P0-1, P1-1 through P1-9) were fixed in
Phase 18A** ("Fix/Delete Cycle for P0/P1") and have been removed from
this document per `CONTRIBUTING.md`'s "remove resolved problems from
the problems file" rule -- each was demonstrated fixed with a real,
executed test before being deleted (never speculatively). See
`ROADMAP.md`'s "Phase 18A — what was actually delivered" section for
the full per-finding root-cause/fix/regression-test summary, and:

- P0-1 → `control_plane.platform.auth`, `docs/adr/0018-minimal-jwt-identity-layer-for-rbac.md`
- P1-1 → `THREAT_MODEL.md` (revised), `SECURITY.md`
- P1-2 → `control_plane.platform.rbac.Permission.RUN_SCHEDULER`, `api/v1/lifecycle.py`
- P1-3 → `services/control-plane/alembic.ini`, `migrations/`
- P1-4 → `frontend/src/api/audit.ts`/`evidence.ts`/`governance.ts`, `AuditTrailPage.tsx`
- P1-5 → `control_plane.platform.logging_config`, `ARCHITECTURE.md` section 3.3
- P1-6 → `data_plane.masking.dataset_masker`'s `_atomic_write_via`/`_atomic_text_writer`
- P1-7 → `control_plane.platform.evidence_signing`, `docs/TAMPER_EVIDENCE_LIMITATIONS.md`
- P1-8 → `POST /api/v1/lifecycle/dataset-versions/governed`, `docs/adr/0019-governed-vs-ungoverned-dataset-version-registration.md`
- P1-9 → `data_plane.certification.gates.check_distribution_shape`

## Phase 18B resolution note

**Phase 18B ("Fix/Delete Cycle for P2/P3") resolved 12 of the 23
remaining P2/P3 findings and narrowed/re-verified 8 more, leaving 11
open with updated, current reasoning** (11, not 8, because a "narrowed"
finding is left open with new text, not deleted). See `ROADMAP.md`'s
"Phase 18B — what was actually delivered" section for the full
per-finding accounting. Six of the twelve deletions (P2-1, P2-2, P2-3,
P2-10, P2-11, P2-12) were fixes completed in an earlier working session
that was interrupted before this bookkeeping step; each was independently
re-verified (tests re-run, diffs re-read) before being deleted here, not
taken on faith from that earlier session's own notes:

- P2-1 → `control_plane.db.session.get_engine_for_url`, `control_plane.db.models.create_postgres_engine`, `data_plane.reference_data.postgres_models.create_postgres_engine`
- P2-2 → `control_plane.platform.scheduler_lock`, `control_plane.db.models.SchedulerLockRow`
- P2-3 → `scripts/run_scheduled_maintenance.py`
- P2-9 → `scripts/check_doc_code_citations.py`
- P2-10 → `infra/terraform/aws/main.tf`
- P2-11 → `services/governance-service/src/governance_service/audit/__init__.py`
- P2-12 → `.dockerignore`, `frontend/.dockerignore`
- P3-3 → `control_plane.domain.capacity.scenario_history.CapacityScenarioHistoryRepository`, `POST/GET /api/v1/capacity/illustrative-plan/history`
- P3-4 → `healthcare_tdm_contracts.CONSUMER_REQUEST_STATUS_TRANSITIONS`, `POST /api/v1/governance/consumer-requests/{id}/reject`/`.../cancel`
- P3-7 → `healthcare_tdm_contracts.MaskingRunSummary`
- P3-8 → `CHANGELOG.md`, every workspace package bumped to `0.2.0`
- P3-9 → `services/data-plane/tests/conftest.py`'s `record_skip_guard_fired` fixture

Narrowed-but-left-open (real work delivered; genuine residual gap
honestly restated, not hidden): P2-4, P2-13, P3-2, P3-10. Re-verified
accurate, left open with fresh evidence: P3-1. Deliberately not built,
left open with reasoning citing precedent (P2-5, P2-6, P2-7, P2-8, P3-5,
P3-6): each names a disproportionately large, previously-deferred build
(a real storage adapter, real NLP-based PHI detection, Spark job
orchestration/real Delta writes, a full frontend CRUD workflow) that
`docs/problems/problems_master.md` P0-3, `docs/problems/problems_phase_08.md` P8-3, and
`docs/problems/problems_phase_14.md` P14-1/P14-4/P14-5 already correctly declined to
build for the same reasons.

## Severity summary

| Severity | Count |
|---|---|
| P0 | 0 (resolved in Phase 18A) |
| P1 | 0 (resolved in Phase 18A) |
| P2 | 6 (was 13; 7 fixed-and-deleted this phase: P2-1, P2-2, P2-3, P2-9, P2-10, P2-11, P2-12) |
| P3 | 5 (was 10; 5 fixed-and-deleted this phase: P3-3, P3-4, P3-7, P3-8, P3-9) |
| **Total remaining** | **11** (was 23; 12 fixed-and-deleted this phase) |

---

## Test suite: real results (run today, not assumed)

**This table is Phase 17's own snapshot, kept as-is for historical
accuracy of what Phase 17 actually ran and verified.** Phase 18A added
substantial new test coverage on top of it (new auth/migration/logging/
atomic-write/distribution-shape/frontend tests), and Phase 18B added
further coverage on top of that (scheduler-lock/pooling/citation-check/
governance-terminal-state/masking-contract/capacity-history/skip-guard/
entity-context tests) — see `ROADMAP.md`'s "Phase 18A — what was
actually delivered" and "Phase 18B — what was actually delivered"
sections for the current, post-Phase-18B pass counts across all four
Python packages and the frontend, run and reported fresh rather than
assumed to still match this table.

| Package | Command | Result |
|---|---|---|
| `libs/contracts` | `python -m pytest -q` | **62 passed**, 0.27s |
| `services/control-plane` | `python -m pytest -q` | **195 passed**, 42.28s |
| `services/data-plane` | `python -m pytest -q` | **439 passed**, 54.71s |
| `services/governance-service` | `python -m pytest -q` | **2 passed**, 0.29s |
| **Total** | | **698 passed, 0 failed, 0 skipped, 0 xfail** |
| `frontend` (Vitest) | `npm test -- --run` | **39 passed** (11 files) |
| `frontend` lint | `npm run lint` | 0 errors |
| `frontend` build | `npm run build` | passes, 285KB bundle (89KB gzip) |

This **exactly matches** the 698 figure `docs/problems/problems_phase_15.md` claimed and is
consistent with the growth trajectory documented since Phase 12 (644→645→...→698).
No regression, no hidden skip masking a real failure. Three `pytest.skip(...)`
calls exist in `services/data-plane` (seed/scale-dependent data-availability
guards in `tests/subsetting/test_selection.py:112` and
`tests/masking/test_dataset_masker_against_real_estate.py:187,198`) — none
fired in this run (all guard conditions were false at the current seed), and
none is a `@pytest.mark.skip`/`xfail` decorator hiding a known regression.
This claim (698, real, reproducible) is itself worth recording as a
**positive** finding: it is one of the only claims checked in this review
that required no correction.

---

## P2 findings

### P2-4 — `size_bytes`/`row_counts` are trusted as caller-supplied at dataset-version registration, never independently re-derived (PARTIALLY RESOLVED, Phase 18B)

- **Problem (original, `row_counts` half now closed for the GOVERNED
  path):** Already tracked as `docs/problems/problems_phase_07.md` P7-8 and
  `docs/problems/problems_phase_08.md` P8-2. Both `size_bytes` and `row_counts` were
  pure caller-supplied claims at dataset-version registration, with no
  cross-check against anything the certification pipeline itself had
  measured.
- **What Phase 18B actually closed:** `CertificationReport.row_count_reconciliation`
  (built by `data_plane.certification.pipeline._build_row_count_trail`
  from a real `final_estate.row_counts()` read of the final estate on
  disk, per entity, as `"source=X selected=Y final=Z"`) was already an
  *available*, already-governed, non-caller-supplied source of exactly
  the numbers `row_counts` claims. `POST /api/v1/lifecycle/dataset-versions/governed`
  (the GOVERNED registration path, ADR-0019) now parses each entity's
  `"final=<N>"` component
  (`control_plane.api.v1.lifecycle._independently_derived_row_counts`)
  and refuses registration with HTTP 409 if the caller-supplied
  `row_counts[entity]` disagrees with it, for every entity the trail
  covers -- mirroring ADR-0019's own "never trust the caller's claim,
  re-derive it from an already-governed source" pattern, applied here to
  row counts instead of policy approval. Proven by
  `test_governed_registration_rejects_a_row_counts_claim_that_contradicts_the_reports_own_trail`
  and two adjacent tests in `test_lifecycle_governed_registration.py`.
- **What remains genuinely open (not closed, not fabricated shut):**
  (1) the pre-existing UNGOVERNED `POST /api/v1/lifecycle/dataset-versions`
  endpoint is deliberately unchanged (per ADR-0019's own blast-radius
  reasoning -- every pre-Phase-10 demo script/tutorial/test calls it and
  none populates `row_count_reconciliation` in a way this check could
  universally rely on); (2) an entity absent from
  `row_count_reconciliation` (e.g. a hand-built report, or an entity the
  trail simply does not mention) has nothing to cross-check against and
  is still accepted as pure caller-supplied claim, by design -- this
  function never invents a count it cannot actually read back out of the
  report; (3) `size_bytes` has **no** equivalent already-measured field
  anywhere in `CertificationReport` at all -- `data_plane.capacity.footprint.measure_directory_footprint`
  computes a real byte size, but only the demo script calls it, and
  nothing threads that measurement into the certification report or any
  artifact the control plane can read back. Re-deriving `size_bytes`
  would need either a real control-plane-side storage adapter (P2-5,
  deliberately not built this phase either) or a new report field wired
  through the whole certification pipeline -- both disproportionate for
  this fix cycle.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/lifecycle.py`,
  `services/control-plane/tests/test_lifecycle_governed_registration.py`.

### P2-5 — No storage adapter exists anywhere; `vacuum_candidates` and object-storage deletion are both purely conceptual (left open, deliberate Phase 18B scope decision)

- **Problem:** Already tracked as `docs/problems/problems_master.md` P0-3 (open since
  Phase 0) and `docs/problems/problems_phase_08.md` P8-3. Confirmed unchanged through
  Phase 18B — `libs/contracts` documents the intended storage adapter
  contract, but no MinIO/S3/ADLS adapter has ever been implemented; every
  data-plane job still reads/writes a local filesystem path directly.
- **Risk:** Low for this portfolio system (local filesystem is a legitimate
  substitute at demo scale). Real for anything claiming cloud-portability —
  `ARCHITECTURE.md` section 2.6's "same job code runs unmodified in any
  environment" claim for storage is aspirational, not exercised.
- **Phase 18B decision:** Deliberately not built. A real storage adapter is
  the same disproportionately large, previously-deferred build the Phase
  18B brief itself named as out of scope for this fix cycle (a genuine
  MinIO/S3/ADLS client abstraction, wired through every data-plane job and
  the control plane's artifact repositories, is multi-phase-sized work, not
  a fix-and-delete item). Building a toy/fake version just to close this
  line item would misrepresent the platform's real capability, which
  `CONTRIBUTING.md`'s honesty rule and this project's own precedent (P0-3
  has stayed open, honestly, since Phase 0) both forbid. Re-confirmed this
  phase: still zero MinIO/S3/ADLS client code anywhere in `services/data-plane`
  or `services/control-plane` (`grep -rn "boto3\|azure.storage\|minio"` across
  both packages' `src/` returns nothing).
- **Reproduction/evidence:** as documented in P0-3.
- **Recommended fix:** as already named — not currently scheduled by name;
  the natural prerequisite for closing P2-4/P1-3-adjacent gaps.
- **Affected files:** `libs/contracts/src/healthcare_tdm_contracts/`.

### P2-6 — Free-text/NLP-based PHI detection is entirely unbuilt and untested (left open, deliberate Phase 18B scope decision)

- **Problem:** Already tracked as `docs/problems/problems_phase_02.md` P2-2 and explained
  at length in `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` section 2 (named
  there as "the single largest reason this is not a de-identification
  guarantee"). Confirmed unchanged: none of the 14 Phase 1 entities has a
  free-text clinical-note field, so the discovery engine's regex/schema-based
  approach has never been exercised against the hardest real-world PHI
  detection case.
- **Risk:** Documented everywhere this repository discusses classification
  limits; not a new risk, but worth restating as one of the highest-value
  P2s precisely because it is the platform's own stated single biggest gap.
- **Phase 18B decision:** Deliberately not built. A real NLP/NER-based PHI
  detector (plus a genuinely representative free-text clinical-note field
  added to the reference estate to exercise it against) is exactly the
  disproportionately large, previously-deferred build the Phase 18B brief
  named as out of scope -- fabricating a toy regex-dressed-up-as-NLP
  detector just to close this line item would misrepresent the platform's
  real classification capability, contradicting the very honesty rule
  `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` exists to uphold. Re-confirmed
  this phase: still zero NLP/NER dependencies or code anywhere in
  `services/data-plane` (`grep -rn "spacy\|nltk\|transformers\|scispacy"` across
  `services/data-plane/src` returns nothing), and the 14 Phase 1 entities
  still have no free-text field.
- **Reproduction/evidence:** as documented in P2-2/`PHI_PII_CLASSIFICATION_LIMITATIONS.md`.
- **Recommended fix:** as already named — add a free-text field to the
  reference estate and an NLP/NER-based detector, explicitly out of scope
  for a regex/schema-based engine per this project's own honesty rule.
- **Affected files:** `services/data-plane/src/data_plane/reference_data/domain.py`,
  `services/data-plane/src/data_plane/discovery/`.

### P2-7 — Neither Spark job is wired into any job orchestrator, and the pandas-vs-Spark masking comparison is not apples-to-apples (left open, deliberate Phase 18B scope decision)

- **Problem:** Already tracked as `docs/problems/problems_phase_14.md` P14-4/P14-5.
  Confirmed unchanged: `data_plane.spark.masking_job`/`subsetting_job` are
  real, tested, but only invocable via CLI/direct import; `spark_masking[claim]`
  masks 2 columns/1 technique vs. pandas's full 14-entity/8-technique run.
- **Risk:** Low (both limitations are honestly and prominently documented in
  `docs/SCALE_AND_PERFORMANCE.md` and `docs/interview/scaling.md`, and
  neither invalidates the real, measured throughput-curve finding).
- **Phase 18B decision:** Deliberately not built. Wiring either Spark job
  into a real job orchestrator (Airflow/Databricks Jobs/a Kubernetes
  CronJob) would need real orchestrator infrastructure this repository has
  no cluster to run against (the same ADR-0012/ADR-0017 boundary
  `scripts/run_scheduled_maintenance.py`'s own docstring restates for the
  Phase 18B P2-3 fix); reimplementing Phase 3's full 14-entity/8-technique
  masking policy in Spark, just to make the comparison "fair," is exactly
  the disproportionately large build `docs/problems/problems_phase_14.md` P14-5 already
  declined for good reason (out of Phase 14's real scope). Both remain
  honestly documented limitations, not silently-dropped ones.
- **Reproduction/evidence:** as documented in P14-4/P14-5.
- **Recommended fix:** as already named — out of Phase 14's scope by design.
- **Affected files:** `services/data-plane/src/data_plane/spark/masking_job.py`,
  `services/data-plane/src/data_plane/spark/subsetting_job.py`.

### P2-8 — No real Delta Lake write exists anywhere despite ADR-0007 choosing Delta for versioned/mutable tables (left open, deliberate Phase 18B scope decision)

- **Problem:** Already tracked as `docs/problems/problems_phase_14.md` P14-1. Confirmed
  unchanged.
- **Risk:** Low (honestly documented; `delta-spark` remains a declared,
  unwired dependency by deliberate choice, not oversight).
- **Phase 18B decision:** Deliberately not built. A real Delta Lake write
  needs a cached Delta Maven artifact that ADR-0017 itself says cannot be
  assumed present in every review environment -- exactly the infrastructure
  boundary this repository has correctly, repeatedly declined to cross
  (restated as recently as this phase's own `docs/SCALE_AND_PERFORMANCE.md`
  section 6, re-verified under P3-1 above). Re-confirmed this phase:
  `delta-spark` remains declared in `services/data-plane/pyproject.toml`
  but `grep -rn "delta" services/data-plane/src/data_plane/spark/` still
  finds no import of it anywhere in real job code.
- **Reproduction/evidence:** as documented in P14-1.
- **Recommended fix:** as already named — a later phase that actually needs
  Delta's ACID/time-travel semantics should close this.
- **Affected files:** `services/data-plane/src/data_plane/spark/`.

### P2-13 — `PolicyApproval`/`performed_by` and every other actor-attribution field remain unverified free text platform-wide (NARROWED, Phase 18B; the big gap remains genuinely open)

- **Problem (original):** Already tracked in scattered form across
  `docs/problems/problems_phase_07.md` P7-6, `docs/problems/problems_phase_10.md` P10-2,
  `docs/problems/problems_phase_11.md` P11-4, `docs/problems/problems_phase_13.md` P13-3, and
  `control_plane.platform.rbac`'s own module docstring. This is the same
  underlying fact as P0-1, restated here at the "audit trail integrity"
  category level: every `AuditEvent.actor`, `revoked_by`, `performed_by`,
  `requested_by`, `generated_by`, and `accessed_by` value in the entire
  audit trail (the primary artifact `docs/COMPLIANCE_EVIDENCE.md` says an
  organization would present to an auditor) is caller-supplied free text
  with no identity verification behind any of it.
- **What Phase 18B actually closed:** Phase 18A (ADR-0018) already added
  a real, verified bearer-token identity (`AuthenticatedActor`,
  `Depends(get_current_actor)`) to every RBAC-gated mutation endpoint --
  but four of those endpoints (`approve_policy_version`,
  `reject_policy_version`, `revoke_dataset_version`,
  `rollback_environment_request`) still recorded the *audit event's own
  `actor` field* from the unverified `body.performed_by`/`body.revoked_by`
  free text instead of the verified identity already sitting right there
  in the request (`actor.username`), even though the RBAC-denial branch
  of each of those same four endpoints already correctly used
  `actor.username`. Phase 18B closed that specific inconsistency: all
  four now record `actor=actor.username` (the cryptographically verified
  identity) on the "allowed"-outcome audit event, with the free-text
  field preserved unchanged in `detail` (e.g. `detail.performed_by`) for
  informational/business-context purposes -- proven by
  `test_approve_and_reject_policy_version_audit_events_record_the_verified_identity_not_free_text`
  (`test_governance_api.py`) and
  `test_revoke_and_rollback_audit_events_record_the_verified_identity_not_free_text`
  (`test_lifecycle_api.py`).
- **Why this is a real, proportionate narrowing, not the whole fix:**
  this only applies to the four endpoints that already require RBAC
  authentication -- there is no verified actor to substitute in for any
  endpoint that has no `Depends(get_current_actor)` at all (`submit_consumer_request`,
  `fulfill_consumer_request`/`reject_consumer_request`/`cancel_consumer_request`,
  `register_dataset_version`/`register_dataset_version_governed`'s
  `created_by`, `record_dataset_version_access`'s `accessed_by`,
  evidence-package `generated_by` -- P13-3's still-open "not RBAC-gated"
  gap). The domain-level `PolicyApproval.performed_by`/
  `DatasetVersionRow.revoked_by` columns themselves are also deliberately
  unchanged (still free text) -- only the *audit trail's* own actor
  attribution moved to the verified identity, which is the
  auditability-specific half of this finding P2-13 was scoped to. A real
  identity provider (ADR-0018's own stated remaining gap) is still the
  only fix that closes every affected field at once; this phase narrowed
  the highest-value slice of it (the audit trail itself, for every
  endpoint where a verified identity already existed to substitute in)
  rather than attempting that whole build.
- **Reproduction/evidence:** as documented across the cited entries; the
  four endpoints' pre-Phase-18B inconsistency (RBAC-denial audit events
  already used `actor.username`; RBAC-allowed audit events did not) was
  independently confirmed by reading `api/v1/governance.py`/`api/v1/lifecycle.py`
  before this phase's fix.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/governance.py`,
  `services/control-plane/src/control_plane/api/v1/lifecycle.py`,
  `services/control-plane/tests/test_governance_api.py`,
  `services/control-plane/tests/test_lifecycle_api.py`,
  `libs/contracts/src/healthcare_tdm_contracts/audit.py`,
  `libs/contracts/src/healthcare_tdm_contracts/evidence.py`,
  `services/control-plane/src/control_plane/platform/rbac.py`.

---

## P3 findings

### P3-1 — Data skew, Delta optimization, and autoscaling remain conceptual, not measured, in Spark documentation (RE-VERIFIED, left open, Phase 18B)

- Already tracked as `docs/problems/problems_phase_14.md` P14-2/P14-1/P14-3. Phase 18B
  re-read `docs/SCALE_AND_PERFORMANCE.md` section 6 ("What is documented
  conceptually, not measured (and why)," lines 151-161) specifically to
  check whether this finding is still accurately, honestly labeled --
  it is: the table there names all three concepts (data skew, Delta
  `OPTIMIZE`/`ZORDER`/`VACUUM`/transaction log, autoscaling) explicitly
  as "not measured here" with a real, specific reason for each (the
  Phase 1 estate's bounded-random fan-out does not produce realistic
  skew; no real Delta write is executed per ADR-0017; `local[*]` has no
  cluster to autoscale) and cites `data_plane/spark/README.md` and the
  exact `docs/problems/problems_phase_14.md` findings this restates. This is exactly
  the kind of already-adequately-addressed-by-existing-docs finding the
  Phase 18B brief anticipated for this item -- attempting new
  measurement here would require infrastructure (a real skewed dataset
  generator, a real Delta-backed cluster, real autoscaling
  infrastructure) this repository has correctly, deliberately declined
  to build. Left open (not deleted) because the underlying gap -- these
  three concepts remain genuinely unmeasured -- is real and undisputed;
  what Phase 18B confirmed is that the *documentation* accurately
  reflects that gap rather than overclaiming, which is the actual
  substance of what a "production readiness" reviewer would check.
  **Affected files:** `services/data-plane/src/data_plane/spark/README.md`,
  `docs/SCALE_AND_PERFORMANCE.md`.

### P3-2 — Compute-unit-hour/annual-processing-volume estimates remain a hardcoded, unbenchmarked constant (NARROWED, Phase 18B; constant deliberately left unchanged)

- **Original:** Already tracked as `docs/problems/problems_phase_08.md` P8-1. Confirmed
  unchanged going into Phase 18B: Phase 14's real throughput numbers had
  never been fed back into
  `control_plane.domain.capacity.estimator.ROWS_PER_COMPUTE_UNIT_HOUR`.
- **What Phase 18B did:** Added a real, cited order-of-magnitude sanity
  check to this module's own docstring: `docs/SCALE_AND_PERFORMANCE.md`
  section 3's real, measured `pandas_masking[full_estate]` throughput
  (2,681 rows/sec at `performance` scale, the closest real analog to
  this constant's "single-process, row-level, full-fidelity masking
  work" category) converts to ~9.65M rows/hour -- about **1.9x** this
  module's assumed 5,000,000, i.e. the illustrative assumption is
  *conservative* relative to the closest real measurement available, not
  arbitrary. Made this an executable, not just a comment:
  `test_rows_per_compute_unit_hour_stays_within_a_sane_order_of_magnitude_of_the_real_phase_14_measurement`
  (`test_capacity_planner.py`) fails if the constant or the cited real
  number ever drift far enough apart that the docstring's own claim goes
  stale.
- **What remains genuinely open (not fabricated shut):** this is a sanity
  check, not a benchmark of this constant itself -- a real
  "subset+mask+certify pipeline" throughput number would also need to
  include Phase 4 subsetting and Phase 6 certification-gate overhead
  (excluded from the comparison), and would need to run on whatever "one
  compute unit" means in a real deployment, not this repository's
  single-machine `local[*]`/plain-Python dev environment. Replacing the
  constant outright, rather than sanity-checking it, would need that
  real benchmark to exist first -- exactly the gap `docs/problems/problems_phase_08.md`
  P8-1 already named and this phase does not close.
- **Affected files:** `services/control-plane/src/control_plane/domain/capacity/estimator.py`,
  `services/control-plane/tests/test_capacity_planner.py`.

### P3-5 — No frontend UI exists for Phase 10 governance at all (left open, deliberate Phase 18B scope decision)

- **Problem:** Already tracked as `docs/problems/problems_phase_10.md` P10-4. Re-confirmed
  this phase by listing `frontend/src/pages/` directly: still no
  `Governance`/`ConsumerRequests`-named page or nav entry anywhere (17
  page files, none named or scoped to Phase 10 governance).
- **Phase 18B decision:** Deliberately not built. A full governance UI
  (business-consumer management, policy-version approval workflow,
  consumer-request submission/fulfillment/reject/cancel screens) is a
  multi-page CRUD frontend feature -- exactly the disproportionately large
  build the Phase 18B brief named as out of scope (it groups this with
  P3-6 below as the same category of deferred frontend write-workflow
  build). Note Phase 18B *did* add real backend capability this UI would
  eventually surface (P3-4's REJECTED/CANCELLED terminal states) and kept
  `frontend/src/api/types.ts`'s `ConsumerDatasetRequest`/`ConsumerRequestStatus`
  mirror in sync with it (see P3-4's entry above) -- so a future phase that
  does build this UI starts from an accurate contract, but building the
  UI itself remains out of this phase's proportionate scope.
- **Affected files:** `frontend/src/pages/`.

### P3-6 — Console remains read-only; no in-UI write workflows for any lifecycle mutation (left open, deliberate Phase 18B scope decision)

- **Problem:** Already tracked as `docs/problems/problems_phase_09.md` P9-2. Re-confirmed
  this phase: `lifecycleApi.revokeDatasetVersion`/`runRefresh`/
  `rollbackEnvironmentRequest` still exist in `frontend/src/api/lifecycle.ts`
  but no page or E2E test invokes any of them; `governance.ts`'s frontend
  client remains read-only too (`listConsumerRequests`/`getConsumerRequest`
  only -- no `fulfillConsumerRequest`/`rejectConsumerRequest`/
  `cancelConsumerRequest` call, even though Phase 18B added all three
  backend endpoints this phase).
- **Phase 18B decision:** Deliberately not built. A real in-UI write
  workflow (forms, confirmation dialogs, optimistic/error UI state, new
  E2E specs) for even one of these mutations is a genuine frontend
  feature-build, not a fix-and-delete item -- the same disproportionate-
  build category as P3-5. Building a token write button with no real
  state handling just to close this line item would be exactly the kind
  of toy fix the Phase 18B brief warned against.
- **Affected files:** `frontend/src/pages/EnvironmentProvisioningPage.tsx`,
  `frontend/src/pages/DatasetDetailPage.tsx`, `frontend/src/api/governance.ts`.

### P3-10 — `pattern:npi`/name-based detectors cannot distinguish a business identifier from a personal one without schema context (NARROWED, Phase 18B; structural limitation remains genuinely open)

- **Problem (original):** Already tracked as `docs/problems/problems_phase_02.md` P2-1
  and explicitly, honestly documented in
  `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` section 1: `pattern:npi`
  cannot tell whether an NPI-shaped column belongs to a provider
  (business identifier) or a person in some other role, from the column
  name alone.
- **What Phase 18B actually closed:** `ColumnToClassify.entity` (the
  owning entity name, already threaded through
  `ClassificationEngine._auto_classify` for the schema-based layer) was
  never passed to the pattern-based fallback layer at all --
  `pattern_rules.match_all` had no entity-context parameter, so even
  when the caller *did* know the owning entity was a recognized business
  entity (`Provider`, `Pharmacy`), a schema-drifted/renamed NPI-like
  column still got the same generic, low-context guess as a truly novel
  source system would. `match_all` now accepts an `entity` parameter
  (threaded from `ClassificationEngine`); when `entity` is one of the
  two business entities this repository's own schema already recognizes
  (`data_plane.discovery.pattern_rules.BUSINESS_ENTITY_NAMES`), a
  matching `pattern:npi` hit is now a confidence-boosted (0.7 -> 0.95),
  reason-clarified `pattern:npi+entity_context` hit instead -- real
  schema-level context resolving the exact ambiguity `pattern:npi`'s own
  reason names, for this one case. Category is deliberately unchanged
  (still PII) -- this narrows the *confidence/reasoning* gap, it does not
  invent a claim that a provider identifier is safe. Proven by
  `test_npi_detector_boosts_confidence_and_clarifies_reason_with_known_business_entity_context`
  and two adjacent tests (`test_pattern_rules.py`), plus an end-to-end
  proof through `ClassificationEngine` itself
  (`test_rule_based_fallback_uses_entity_context_for_a_drifted_npi_column`,
  `test_engine.py`).
- **What remains genuinely open (the real, structural half of this
  finding):** a truly novel source system whose entity name this
  repository's schema has never seen at all (not `Provider`/`Pharmacy`,
  not any of the other 12 known entities either) still gets the
  unmodified, low-context, name-only guess -- entity-name recognition is
  itself necessarily a fixed, finite list, not semantic understanding.
  This is the same limitation every schema-based mechanism in this
  engine already has, restated rather than solved: no amount of
  additional hardcoded entity names turns a regex into contextual
  understanding of data it has never been told about. Free-text/NLP
  detection (P2-6, deliberately not built either) is the only mechanism
  that would meaningfully close the remaining gap, and it is out of
  proportionate scope for the same reason P2-6 is.
- **Affected files:**
  `services/data-plane/src/data_plane/discovery/pattern_rules.py`,
  `services/data-plane/src/data_plane/discovery/engine.py`,
  `services/data-plane/tests/discovery/test_pattern_rules.py`,
  `services/data-plane/tests/discovery/test_engine.py`,
  `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`.

---

## What this review did NOT find

For completeness, several categories the Phase 17 brief lists were
inspected and found to have **no new findings beyond what prior phases
already, correctly, closed or documented as acceptable**:

- **Referential integrity**: `data_plane.subsetting.closure`'s three-way
  orphan classification (`engine_bug`/`source_orphan`/`negative_test_injection`)
  and `data_plane.certification.gates.check_referential_integrity`'s
  independent re-derivation both hold up under direct inspection; no new
  gap found.
- **Certification**: all eleven gates (`check_phi_pii_policy_coverage`,
  `check_masking_completion`, `check_referential_integrity`,
  `check_orphan_detection`, `check_schema_validation`,
  `check_data_quality_thresholds`, `check_row_count_reconciliation`,
  `check_provenance`, `check_manifest_generation`,
  `check_policy_version_recorded`, `check_masking_version_recorded`) exist
  exactly as documented, confirmed by direct read of `gates.py`.
- **Docker/K8s/Helm/Terraform consistency with Phase 13/14**: confirmed, via
  `git log --oneline -- infra/`, that `infra/` was touched only in Phase 0
  and Phase 12 — neither Phase 13 (evidence) nor Phase 14 (Spark) needed an
  infra change, and this is a documented, deliberate decision (Phase 14
  stayed `local[*]`-only per ADR-0017) rather than silent drift. Health
  probes correctly point at the real `/api/v1/health`/`/api/v1/ready`
  endpoints in both the Helm chart and `docker-compose.yml`. No hardcoded
  production credentials found in either Terraform example; the Postgres/MinIO
  dev credentials in `docker-compose.yml`/`.env.example` are consistent,
  clearly-labeled placeholders, never presented as production-ready.
- **CI/CD security gating**: `scripts/security/dependency_scan.py` and
  `detect_secrets.py` are both confirmed wired into `.github/workflows/ci.yml`'s
  `security-checks` job (resolving `docs/problems/problems_phase_11.md` P11-3, as Phase 12
  claimed) and gate the `release-gate` job; `container-build.yml` additionally
  runs Trivy image scanning, a previously-undocumented-in-the-phase-docs
  extra layer.
- **npm dependency vulnerabilities**: `npm audit` reports zero
  vulnerabilities (0 info/low/moderate/high/critical) across 485 dependencies.
- **Test suite integrity**: the claimed 698-test baseline is real,
  reproducible, and accurate today (see "Test suite: real results" above) —
  this was the one major claim checked in this review that required no
  correction at all.

---

## How severity was assigned

- **P0** — a finding that either (a) actively misrepresents the platform's
  real behavior in a way that would mislead a reader/auditor about safety or
  security, or (b) means a headline architectural control (here: RBAC)
  provides categorically less protection than its own documentation implies,
  even though the *practical* risk today is zero (synthetic data, no
  deployment). Reserved for the single most consequential finding.
- **P1** — a real, concrete gap in a production-critical control
  (authentication context, schema migrations, tamper-evidence, governance
  enforcement, observability, frontend-backend parity) that this review
  independently judges would block a genuine production deployment, even
  where it has already been honestly disclosed by an earlier phase.
- **P2** — a real gap that is lower-blast-radius, already substantially
  mitigated by an adjacent control, or affects a secondary/illustrative
  capability rather than the core pipeline.
- **P3** — a documented, deliberate scope boundary, a cosmetic/documentation
  accuracy issue, or a low-priority feature gap with no realistic path to
  causing harm even in a hypothetical production deployment.

Severity reflects real risk to *this system's actual, stated purpose* — a
portfolio-grade, honestly-documented reference implementation using only
synthetic data, not a live system holding real PHI. Every P0/P1 above is
explicit about what is and is not actually at stake today versus in a
hypothetical real deployment, per the review brief's own instruction not to
manufacture panic where none is warranted, and not to downplay a real
architectural gap just because no real PHI is at risk today.
