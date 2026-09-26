# Phase 17 — Principal-Engineer Production Readiness Review

**Scope:** review only. No application code, infrastructure, or documentation
other than this file was changed while producing it. Per the Phase 17 prompt:
*"Do not fix anything yet. STOP."* Nothing below has been fixed — this is the
input Phase 18A/18B will fix or delete from.

**Method.** Before writing a single finding, this review read: `ARCHITECTURE.md`,
all 17 ADRs, every `problems_phase_01.md`-`problems_phase_15.md` (there is no
`problems_phase_16.md` — `ROADMAP.md`'s own Phase 16 section explains why, and
that explanation was verified rather than assumed), `problems_master.md`,
`docs/PLATFORM_INTEGRITY.md`, `docs/CERTIFICATION_VS_MASKING.md`,
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`, `docs/CAPACITY_COST_TRADEOFFS.md`,
`docs/COMPLIANCE_EVIDENCE.md`, `docs/SCALE_AND_PERFORMANCE.md`,
`docs/AZURE_PRODUCTION_DEPLOYMENT.md`, all four `docs/interview/*.md`,
`docs/runbooks/*.md`, `SECURITY.md`, `THREAT_MODEL.md`, `DATA_GOVERNANCE.md`,
`CONTRIBUTING.md`, `README.md`. Then, rather than trusting that prior art,
every category the prompt lists was independently re-inspected against the
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
an existing `problems_phase_NN.md`/`problems_master.md` entry, that entry is
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

The P2/P3 findings below are **unchanged** from the original Phase 17
review -- Phase 18A's scope was P0/P1 only, per its own phase prompt
("Work ONLY on P0 and P1 issues... When all P0/P1 issues are resolved,
STOP"). They remain open, tracked here exactly as Phase 17 left them,
for a future Phase 18B.

## Severity summary

| Severity | Count |
|---|---|
| P0 | 0 (resolved in Phase 18A) |
| P1 | 0 (resolved in Phase 18A) |
| P2 | 13 |
| P3 | 10 |
| **Total** | **23** |

---

## Test suite: real results (run today, not assumed)

**This table is Phase 17's own snapshot, kept as-is for historical
accuracy of what Phase 17 actually ran and verified.** Phase 18A added
substantial new test coverage on top of it (new auth/migration/logging/
atomic-write/distribution-shape/frontend tests) — see `ROADMAP.md`'s
"Phase 18A — what was actually delivered" section for the current,
post-Phase-18A pass counts across all four Python packages and the
frontend, run and reported fresh rather than assumed to still match
this table.

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

This **exactly matches** the 698 figure `problems_phase_15.md` claimed and is
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

### P2-1 — Control-plane's Postgres engine has no connection-pool resilience configuration (new finding)

- **Problem:** `create_postgres_engine`/`create_engine` calls throughout
  `control_plane/db/models.py:333`, `control_plane/db/session.py:43`, and
  `data_plane/reference_data/postgres_models.py:206` all call
  `create_engine(database_url)` with zero pool arguments — no
  `pool_pre_ping=True`, no explicit `pool_size`/`max_overflow`/`pool_recycle`.
  Without `pool_pre_ping`, a connection that has gone stale (e.g. after a
  Postgres restart, a load balancer idle-timeout, or a cloud-managed
  Postgres failover) is not detected until a query using it fails, rather
  than being transparently recycled.
- **Risk:** For this portfolio system: none (SQLite is the default and only
  exercised backend in this environment; connections are short-lived
  per-test). For a real deployment: a real, if minor and easily fixed, class
  of transient-error exposure.
- **Reproduction/evidence:** `grep -rn "create_engine(" services/` → all six
  call sites pass only the URL, no keyword arguments.
- **Recommended fix:** Add `pool_pre_ping=True` (and, for a real deployment,
  sensible `pool_size`/`max_overflow` defaults) to `create_postgres_engine`.
- **Affected files:** `services/control-plane/src/control_plane/db/models.py`,
  `services/control-plane/src/control_plane/db/session.py`.

### P2-2 — No distributed lock on concurrent scheduler sweeps

- **Problem:** Already tracked as `problems_phase_07.md` P7-2, restated in
  `docs/runbooks/duplicate-requests-and-revoked-datasets.md`'s "the one gap
  this does NOT close" section and `docs/interview/scaling.md`. Confirmed
  unchanged: two concurrent calls to `POST /api/v1/lifecycle/scheduler/run-due`
  have no application-level lock preventing an overlapping sweep.
- **Risk:** Low for this portfolio system (SQLite serializes writes at the
  file level; no concurrent caller exists in any test/demo). Real for a
  production deployment with more than one scheduler instance or an
  overlapping retry.
- **Reproduction/evidence:** as documented in P7-2: call `run-due` twice in
  rapid succession against a request whose `next_refresh_at` is in the past.
- **Recommended fix:** as P7-2 already names: rely on the external
  scheduler's own concurrency control (Airflow single-active-DAG-run,
  Kubernetes CronJob `concurrencyPolicy: Forbid`) — combine with P1-2's
  recommendation to also gate this endpoint by RBAC.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/scheduler.py`.

### P2-3 — Retention sweep and vacuum-candidate identification have no automatic trigger

- **Problem:** Already tracked as `problems_phase_07.md` P7-3 and
  `problems_phase_08.md` P8-3. Confirmed unchanged: `apply_retention` and
  `vacuum_candidates` are both real, correct, callable methods with no
  cron/daemon/scheduled-task caller anywhere in the repository.
- **Risk:** Low (both are read/state-transition-only against already-real
  data; nothing is silently lost by not running them — expired data simply
  isn't flagged as expired until someone calls the method).
- **Reproduction/evidence:** as documented in P7-3/P8-3.
- **Recommended fix:** as already named — a future scheduler-deployment
  phase.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`,
  `services/control-plane/src/control_plane/domain/capacity/planner.py`.

### P2-4 — `size_bytes`/`row_counts` are trusted as caller-supplied at dataset-version registration, never independently re-derived

- **Problem:** Already tracked as `problems_phase_07.md` P7-8 and
  `problems_phase_08.md` P8-2. Confirmed unchanged.
- **Risk:** Low (no adversarial caller exists; real measurement tooling
  exists in `data_plane.capacity.footprint` and is used by the demo script,
  just not enforced).
- **Reproduction/evidence:** as documented in P7-8/P8-2.
- **Recommended fix:** as already named — would need a control-plane-side
  storage adapter or a job-orchestration step that runs the measurement and
  passes verified output to registration.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`.

### P2-5 — No storage adapter exists anywhere; `vacuum_candidates` and object-storage deletion are both purely conceptual

- **Problem:** Already tracked as `problems_master.md` P0-3 (open since
  Phase 0) and `problems_phase_08.md` P8-3. Confirmed unchanged through
  Phase 16 — `libs/contracts` documents the intended storage adapter
  contract, but no MinIO/S3/ADLS adapter has ever been implemented; every
  data-plane job still reads/writes a local filesystem path directly.
- **Risk:** Low for this portfolio system (local filesystem is a legitimate
  substitute at demo scale). Real for anything claiming cloud-portability —
  `ARCHITECTURE.md` section 2.6's "same job code runs unmodified in any
  environment" claim for storage is aspirational, not exercised.
- **Reproduction/evidence:** as documented in P0-3.
- **Recommended fix:** as already named — not currently scheduled by name;
  the natural prerequisite for closing P2-4/P1-3-adjacent gaps.
- **Affected files:** `libs/contracts/src/healthcare_tdm_contracts/`.

### P2-6 — Free-text/NLP-based PHI detection is entirely unbuilt and untested

- **Problem:** Already tracked as `problems_phase_02.md` P2-2 and explained
  at length in `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` section 2 (named
  there as "the single largest reason this is not a de-identification
  guarantee"). Confirmed unchanged: none of the 14 Phase 1 entities has a
  free-text clinical-note field, so the discovery engine's regex/schema-based
  approach has never been exercised against the hardest real-world PHI
  detection case.
- **Risk:** Documented everywhere this repository discusses classification
  limits; not a new risk, but worth restating as one of the highest-value
  P2s precisely because it is the platform's own stated single biggest gap.
- **Reproduction/evidence:** as documented in P2-2/`PHI_PII_CLASSIFICATION_LIMITATIONS.md`.
- **Recommended fix:** as already named — add a free-text field to the
  reference estate and an NLP/NER-based detector, explicitly out of scope
  for a regex/schema-based engine per this project's own honesty rule.
- **Affected files:** `services/data-plane/src/data_plane/reference_data/domain.py`,
  `services/data-plane/src/data_plane/discovery/`.

### P2-7 — Neither Spark job is wired into any job orchestrator, and the pandas-vs-Spark masking comparison is not apples-to-apples

- **Problem:** Already tracked as `problems_phase_14.md` P14-4/P14-5.
  Confirmed unchanged: `data_plane.spark.masking_job`/`subsetting_job` are
  real, tested, but only invocable via CLI/direct import; `spark_masking[claim]`
  masks 2 columns/1 technique vs. pandas's full 14-entity/8-technique run.
- **Risk:** Low (both limitations are honestly and prominently documented in
  `docs/SCALE_AND_PERFORMANCE.md` and `docs/interview/scaling.md`, and
  neither invalidates the real, measured throughput-curve finding).
- **Reproduction/evidence:** as documented in P14-4/P14-5.
- **Recommended fix:** as already named — out of Phase 14's scope by design.
- **Affected files:** `services/data-plane/src/data_plane/spark/masking_job.py`,
  `services/data-plane/src/data_plane/spark/subsetting_job.py`.

### P2-8 — No real Delta Lake write exists anywhere despite ADR-0007 choosing Delta for versioned/mutable tables

- **Problem:** Already tracked as `problems_phase_14.md` P14-1. Confirmed
  unchanged.
- **Risk:** Low (honestly documented; `delta-spark` remains a declared,
  unwired dependency by deliberate choice, not oversight).
- **Reproduction/evidence:** as documented in P14-1.
- **Recommended fix:** as already named — a later phase that actually needs
  Delta's ACID/time-travel semantics should close this.
- **Affected files:** `services/data-plane/src/data_plane/spark/`.

### P2-9 — `ROADMAP.md`'s Phase 16 section and `docs/tutorial/guide/` chapters cite real code paths that a future refactor could silently break, with no automated cross-check (new observation)

- **Problem:** Phase 15's tutorial (20 chapters) and Phase 16's interview
  docs (4 files) both derive their credibility from citing exact module
  paths, CLI flags, API routes, and contract field names against the real
  source tree — verified as accurate by this review's own reading of both
  against the current code (no drift found today). But there is no
  automated test anywhere that fails if a future phase renames, say,
  `data_plane.spark.masking_job.run_claims_masking_job` or changes
  `POST /api/v1/lifecycle/scheduler/run-due`'s path — both `docs/tutorial/guide/`
  and `docs/interview/` would silently go stale exactly the way
  `problems_phase_09.md` P9-5 already documents for `frontend/src/api/types.ts`
  drifting from `libs/contracts`, but for prose rather than a type file, and
  with no CI signal at all (not even a manual-review flag).
- **Risk:** Low today (verified accurate as of this review). Growing over
  time as more phases touch the modules these 24 documentation files cite.
- **Reproduction/evidence:** this review's own cross-check of
  `docs/interview/system-design.md`/`tradeoffs.md`/`failure-scenarios.md`/`scaling.md`
  against `services/control-plane/src/control_plane/api/v1/*.py`,
  `services/data-plane/src/data_plane/spark/`, and `services/control-plane/src/control_plane/platform/rbac.py`
  found zero inaccuracies as of today — this finding is about the *absence
  of a guardrail*, not a present inaccuracy.
- **Recommended fix:** Not urgent enough to warrant new tooling on its own,
  but worth a lightweight periodic "does every code path docs/interview and
  docs/tutorial/guide cite still exist" grep-based check, possibly folded
  into a future documentation-freshness CI step.
- **Affected files:** `docs/interview/*.md`, `docs/tutorial/guide/*.md`.

### P2-10 — `infra/terraform/aws/main.tf`'s header comment cites a phantom "Phase 20" that does not match this repository's real phase history (new finding)

- **Problem:** The file's own header comment (lines 4-6) reads: *"Phase 0
  scope: structural placeholder only... this file exists to fix the
  provider/backend shape so Phase 20 (Kubernetes/Helm + Terraform examples)
  starts from an agreed structure."* No phase in `ROADMAP.md` is described
  that way, anywhere — Helm and the real Terraform example were actually
  built in **Phase 12**. `problems_phase_12.md` confirms Phase 12
  deliberately built out `azure/main.tf` in full while leaving `aws/main.tf`
  "unchanged, still passing" — an intentional asymmetry — but nobody updated
  this file's own in-file comment to reflect that decision.
- **Risk:** None functionally (`terraform validate`/`fmt` both pass per
  Phase 12's own verification); purely a documentation-accuracy issue that
  could mislead a future contributor about which phase to attribute this
  file's design intent to.
- **Reproduction/evidence:** `infra/terraform/aws/main.tf` lines 4-6; a
  repo-wide grep of `ROADMAP.md` for "Phase 20" returns no matches.
- **Recommended fix:** Update the header comment to name Phase 12 and the
  real asymmetry decision, matching `azure/main.tf`'s equivalent (accurate)
  header.
- **Affected files:** `infra/terraform/aws/main.tf`.

### P2-11 — `services/governance-service`'s `audit/__init__.py` placeholder docstring cites the wrong phase for its own eventual implementation

- **Problem:** The module docstring reads: *"Phase 0 scope: placeholder
  module. Implemented in Phase 3."* Audit logging was never implemented in
  `services/governance-service` at all, in Phase 3 or any other phase — it
  was implemented in Phase 11, inside `services/control-plane`
  (`control_plane.platform.audit`), per ADR-0015, precisely because
  `services/governance-service` remains a scaffold. Phase 3 is masking, an
  unrelated capability. This looks like a copy/paste of a sibling
  placeholder module's docstring pattern that was never corrected once the
  real implementation location was decided (ADR-0015 postdates this file).
- **Risk:** None functionally — this is a docstring in an empty placeholder
  module. Purely a small, confusing documentation-accuracy issue for a
  future reader trying to find where audit logging actually lives.
- **Reproduction/evidence:** `services/governance-service/src/governance_service/audit/__init__.py:9`.
- **Recommended fix:** Update the docstring to say "not yet implemented
  here; see `control_plane.platform.audit` (Phase 11) and ADR-0015/ADR-0016
  for why the real implementation lives in `services/control-plane`
  instead," mirroring how `ARCHITECTURE.md` section 2.4 already explains
  this for a reader of that file.
- **Affected files:** `services/governance-service/src/governance_service/audit/__init__.py`.

### P2-12 — `frontend/`'s Dockerfile build context has no `.dockerignore` anywhere in the repository

- **Problem:** No `.dockerignore` file exists at the repo root, in
  `frontend/`, `services/control-plane/`, or `services/governance-service/`.
  `frontend/Dockerfile` does `COPY package.json package-lock.json ./` then
  later `COPY . .` with build context `frontend/` — with no `.dockerignore`,
  a developer's local `node_modules/`, `dist/`, or `test-results/` sitting in
  their `frontend/` checkout would be sent into the Docker build context.
  `services/control-plane`/`governance-service`'s Dockerfiles use explicit
  `COPY libs/contracts`, `COPY services/control-plane`, etc. rather than
  `COPY . .`, so they are not exposed to this specific pattern.
- **Risk:** Low — not a secret-exposure risk (nothing sensitive lives in
  `frontend/node_modules`/`dist`), but wasteful (larger build context sent
  to the Docker daemon) and not best practice; `npm ci` inside the container
  reinstalls regardless, so correctness is unaffected.
- **Reproduction/evidence:** `find . -iname ".dockerignore"` returns nothing
  anywhere in the repository; `frontend/Dockerfile` lines 16-17 (`COPY
  package.json package-lock.json ./`) followed by a later `COPY . .`.
- **Recommended fix:** Add a `.dockerignore` to `frontend/` excluding
  `node_modules`, `dist`, `test-results`, `.env*`.
- **Affected files:** `frontend/Dockerfile` (missing sibling `.dockerignore`).

### P2-13 — `PolicyApproval`/`performed_by` and every other actor-attribution field remain unverified free text platform-wide

- **Problem:** Already tracked in scattered form across
  `problems_phase_07.md` P7-6, `problems_phase_10.md` P10-2,
  `problems_phase_11.md` P11-4, `problems_phase_13.md` P13-3, and
  `control_plane.platform.rbac`'s own module docstring. This is the same
  underlying fact as P0-1, restated here at the "audit trail integrity"
  category level: every `AuditEvent.actor`, `revoked_by`, `performed_by`,
  `requested_by`, `generated_by`, and `accessed_by` value in the entire
  audit trail (the primary artifact `docs/COMPLIANCE_EVIDENCE.md` says an
  organization would present to an auditor) is caller-supplied free text
  with no identity verification behind any of it.
- **Risk:** For this portfolio system: none. For production readiness /
  auditability specifically: an `AuditEvidencePackage`'s entire value
  depends on trusting who did what — and every "who" field in it is
  unverified. This is listed separately from P0-1 because it is specifically
  an *auditability* review-category finding (the evidence itself, not just
  the access-control mechanism), even though the root cause is identical.
- **Reproduction/evidence:** as documented across the cited entries;
  independently confirmed by this review's own reading of
  `healthcare_tdm_contracts.evidence`/`audit` and
  `control_plane.platform.rbac`'s docstrings.
- **Recommended fix:** same as P0-1 — a real identity provider is the only
  fix that closes this for every affected field at once, rather than
  patching each field individually.
- **Affected files:** `libs/contracts/src/healthcare_tdm_contracts/audit.py`,
  `libs/contracts/src/healthcare_tdm_contracts/evidence.py`,
  `services/control-plane/src/control_plane/platform/rbac.py`.

---

## P3 findings

### P3-1 — Data skew, Delta optimization, and autoscaling remain conceptual, not measured, in Spark documentation

- Already tracked as `problems_phase_14.md` P14-2/P14-1/P14-3. Confirmed
  unchanged and honestly labeled as such throughout `docs/SCALE_AND_PERFORMANCE.md`.
  **Affected files:** `services/data-plane/src/data_plane/spark/README.md`.

### P3-2 — Compute-unit-hour/annual-processing-volume estimates remain a hardcoded, unbenchmarked constant

- Already tracked as `problems_phase_08.md` P8-1. Confirmed unchanged;
  Phase 14's real throughput numbers were never fed back into
  `control_plane.domain.capacity.estimator.ROWS_PER_COMPUTE_UNIT_HOUR`.
  **Affected files:** `services/control-plane/src/control_plane/domain/capacity/estimator.py`.

### P3-3 — Illustrative capacity scenarios are stateless; nothing can be saved/compared over time

- Already tracked as `problems_phase_08.md` P8-4. Confirmed unchanged.
  **Affected files:** `services/control-plane/src/control_plane/api/v1/capacity.py`.

### P3-4 — `ConsumerDatasetRequest` has no REJECTED/CANCELLED terminal state

- Already tracked as `problems_phase_10.md` P10-3. Confirmed unchanged; low
  priority as already assessed. **Affected files:**
  `libs/contracts/src/healthcare_tdm_contracts/governance.py`.

### P3-5 — No frontend UI exists for Phase 10 governance at all

- Already tracked as `problems_phase_10.md` P10-4. Confirmed unchanged
  (reconfirmed by this review's own frontend audit — no governance-related
  page or nav entry exists). **Affected files:** `frontend/src/pages/`.

### P3-6 — Console remains read-only; no in-UI write workflows for any lifecycle mutation

- Already tracked as `problems_phase_09.md` P9-2. Confirmed unchanged and
  reconfirmed directly: `lifecycleApi.revokeDatasetVersion`/`runRefresh`/
  `rollbackEnvironmentRequest` exist in `frontend/src/api/lifecycle.ts` but
  no page or E2E test invokes any of them. **Affected files:**
  `frontend/src/pages/EnvironmentProvisioningPage.tsx`, `frontend/src/pages/DatasetDetailPage.tsx`.

### P3-7 — Masking run summary still has no shared `libs/contracts` shape

- Already tracked as `problems_phase_09.md` P9-1. Confirmed unchanged.
  **Affected files:** `services/control-plane/src/control_plane/artifacts/masking.py`.

### P3-8 — No `CHANGELOG` and every workspace package remains pinned at `0.1.0` despite 16 phases of substantial functional change (new observation)

- **Problem:** `libs/contracts`, `services/control-plane`,
  `services/data-plane`, `services/governance-service`, and `frontend` all
  report `version = "0.1.0"` in their respective `pyproject.toml`/`package.json`
  files, unchanged since Phase 0, despite each package having gained
  substantial, real, tested functionality across the phases documented in
  `ROADMAP.md`. There is no `CHANGELOG.md` anywhere recording what shipped
  in which version.
- **Risk:** Purely cosmetic/release-hygiene; has no functional or security
  impact for a repository that has never cut a real release. Worth noting
  only because a "production readiness" review is explicitly the kind of
  exercise that would flag missing release discipline.
- **Reproduction/evidence:** `grep -n "^version" */pyproject.toml frontend/package.json`
  → `0.1.0` everywhere.
- **Recommended fix:** Low priority; adopt semantic versioning and a
  changelog only if/when this repository ever produces a real, externally
  consumed release (e.g. `libs/contracts` published as an installable
  package for a downstream consumer).
- **Affected files:** `libs/contracts/pyproject.toml`,
  `services/control-plane/pyproject.toml`,
  `services/data-plane/pyproject.toml`,
  `services/governance-service/pyproject.toml`, `frontend/package.json`.

### P3-9 — Three `pytest.skip(...)` calls in `services/data-plane` are conditional on generator seed/scale and could silently start skipping without notice (new observation)

- **Problem:** `tests/subsetting/test_selection.py:112` and
  `tests/masking/test_dataset_masker_against_real_estate.py:187,198` each
  contain a runtime `pytest.skip(...)` guarding against a synthetic-data
  edge case not existing at the current random seed/scale (e.g. "no partner
  v2 records generated at this seed/scale"). None fired in this review's
  real test run (all three guard conditions were false, so the underlying
  assertions executed for real this time) — but because they are
  data-dependent rather than environment-dependent, a future change to the
  generator's seed or scale defaults could cause one to start silently
  skipping with no CI signal distinguishing "skipped because the edge case
  legitimately didn't occur this run" from "skipped because a generator
  regression stopped producing this edge case at all."
- **Risk:** Low today (verified not currently skipping); a latent risk that
  a real regression in edge-case generation could hide behind a skip rather
  than a failure.
- **Reproduction/evidence:** file:line citations above; confirmed via the
  real test run performed for this review (439 passed, 0 skipped reported
  by pytest at the current seed).
- **Recommended fix:** Consider asserting a minimum expected count in the
  test setup itself (fail loudly if the edge case has stopped occurring at
  all) rather than skip silently, or at minimum log/count skips in CI so a
  sustained pattern of skipping is visible over time.
- **Affected files:** `services/data-plane/tests/subsetting/test_selection.py`,
  `services/data-plane/tests/masking/test_dataset_masker_against_real_estate.py`.

### P3-10 — `pattern:npi`/name-based detectors cannot distinguish a business identifier from a personal one without schema context

- Already tracked as `problems_phase_02.md` P2-1. Confirmed unchanged and
  explicitly, honestly documented as a structural (not fixable by pattern
  matching alone) limitation in `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`
  section 1. **Affected files:**
  `services/data-plane/src/data_plane/discovery/pattern_rules.py`.

---

## What this review did NOT find

For completeness, several categories the Phase 17 prompt lists were
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
  `security-checks` job (resolving `problems_phase_11.md` P11-3, as Phase 12
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
