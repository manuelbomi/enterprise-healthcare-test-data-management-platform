# Roadmap

This repository is built as a **21-phase promptbook-driven project** (Phase 0
through Phase 17, split fix/delete cycles 18A/18B, and a Final release
phase). Each phase is scoped to be independently completable, testable, and
documented before the next begins. Phases are not sprints with fixed dates —
they are ordered units of work. A phase is not "done" until its required
tests pass (see [`CONTRIBUTING.md`](CONTRIBUTING.md) for the per-phase
process).

This file tracks the *plan*. Day-to-day open issues live in
[`problems_master.md`](problems_master.md). The exact phase prompts this
roadmap follows come from the private planning document that seeded this
project; the table below is the authoritative phase order and scope for this
repository going forward.

## Phase index

| Phase | Theme | Status |
|---|---|---|
| 0 | Repository operating rules, architecture, conventions, ADRs, scaffolding | **Complete** |
| 1 | Synthetic healthcare data estate across 5 heterogeneous source systems | **Complete** |
| 2 | PHI/PII discovery and classification engine + data catalog | **Complete** |
| 3 | Enterprise deterministic masking engine (pseudonymization/tokenization) | **Complete** |
| 4 | Referentially intact, production-scale data subsetting | **Complete** |
| 5 | Synthetic test data generation (scenario/edge-case data) | **Complete** |
| 6 | Certified test dataset pipeline (ingest→...→certify→publish) | **Complete** |
| 7 | Dataset lifecycle and refresh management (versions, cadence, retention) | **Complete** |
| 8 | Storage and compute footprint management / capacity planning | **Complete** |
| 9 | React/TypeScript enterprise TDM web console | **Complete** |
| 10 | Centralized enterprise masking standard (multi-business-unit governance) | **Complete** |
| 11 | Platform integrity (health, resiliency, failure injection) | **Complete** |
| 12 | Production CI/CD and cloud testing (GitHub Actions, K8s, Terraform) | **Complete** |
| 13 | Auditability and compliance evidence | **Complete** |
| 14 | Scale and performance engineering (PySpark benchmarks) | **Complete** |
| 15 | Complete junior-engineer tutorial (20 chapters) | **Complete** |
| 16 | Interview / system design documentation | **Complete** |
| 17 | Principal-engineer production readiness review (findings only, no fixes) | **Complete** |
| 18A | Fix/delete cycle for P0/P1 findings from Phase 17 | **Complete** |
| 18B | Fix/delete cycle for P2/P3 findings from Phase 17 | Not started |
| Final | Recruiter/interviewer-ready release (README rewrite, demo, checklist) | Not started |

## Phase 18A — what was actually delivered

Fixed every P0/P1 finding `problems_final_review.md` (Phase 17) named --
ten findings (P0-1, P1-1 through P1-9) -- following the phase's own
fix/delete discipline: reproduce, fix the root cause, add a regression
test, run the relevant tests, delete the finding only after
demonstrating the fix with real, executed evidence. No P2/P3 finding was
touched (that is Phase 18B's scope, per the phase prompt's own "Work
ONLY on P0 and P1" instruction).

- **P0-1 (RBAC had no real security boundary)** — added
  `control_plane.platform.auth`, a real, deliberately minimal JWT
  issuance/verification layer (`POST /api/v1/auth/login` against a
  small, fixed set of seeded SYNTHETIC demo identities, one per
  `control_plane.platform.rbac.Role`). Every RBAC call site
  (`revoke_dataset_version`, `rollback_environment_request`,
  `approve_policy_version`, `reject_policy_version`) now derives the
  role it authorizes against from a verified bearer token
  (`Depends(get_current_actor)`) instead of a caller-supplied,
  unverified `actor_role` request field, which was removed from every
  affected request body. Signing key follows the repository's
  established `TDM_MASKING_HMAC_KEY`-style convention (env var +
  gitignored `.env` fallback + `--generate-dev-key` CLI helper --
  `TDM_CONTROL_PLANE_JWT_SIGNING_KEY`). See
  [ADR-0018](docs/adr/0018-minimal-jwt-identity-layer-for-rbac.md) for
  the deliberate, documented scope boundary (not a production identity
  provider). Proven by `services/control-plane/tests/test_platform_auth.py`
  (20 tests: login success/failure, token expiry/tamper/wrong-key
  rejection, every RBAC-gated endpoint rejecting a missing token with
  401 before RBAC is even evaluated) plus updated end-to-end RBAC tests
  in `test_lifecycle_api.py`/`test_governance_api.py`/
  `test_failure_injection.py`/`test_capacity_api.py`.
- **P1-2 (`/scheduler/run-due` was the widest-blast-radius unauthenticated
  endpoint)** — added `Permission.RUN_SCHEDULER` (`PLATFORM_ADMIN` only)
  and gated the endpoint the same way as the other four; `triggered_by`
  is now the verified actor's username, not a caller-supplied,
  unverified query parameter defaulting to the literal string
  `"scheduler"`. Proven by new 401/403/200 assertions in
  `test_lifecycle_api.py` and `test_platform_auth.py`.
- **P1-1 (`THREAT_MODEL.md` stale since Phase 0, now false)** — corrected
  the Control plane Spoofing/Denial-of-service/Elevation-of-privilege
  mitigations to describe the real Phase 18A mechanism (or its honest
  absence, for the still-open DoS/quota gap) instead of the fictional
  "token-based auth... on every request" and unwired capacity-planning
  claims; fixed the "Phase 15" → Phase 8 citation; added a revisit-history
  entry. `SECURITY.md` cross-references the same fix.
- **P1-3 (no schema-migration framework)** — added a real Alembic setup
  (`services/control-plane/alembic.ini`, `migrations/env.py`,
  `migrations/versions/8387cacfabb1_phase18a_initial_schema.py`,
  generated via `alembic revision --autogenerate` directly against
  `control_plane.db.models.Base.metadata`, not hand-transcribed).
  `init_schema`/`create_all` remains for the from-scratch (fresh
  test/dev SQLite) path; every future model change gets a new migration
  going forward (documented in `db/models.py` and the control-plane
  README). Proven by `services/control-plane/tests/test_migrations.py`
  (4 tests: `alembic upgrade head` produces exactly the same tables
  `create_all` does, `alembic check` reports zero drift, `downgrade
  base` cleanly reverses it, `upgrade head` run twice is a no-op).
  Fixing this also surfaced and fixed a real, independent bug: Alembic's
  `fileConfig` (default `disable_existing_loggers=True`) was permanently
  disabling this same phase's new `control_plane.request`/
  `control_plane.lifecycle.scheduler` loggers the first time any
  migration ran in-process -- fixed with `disable_existing_loggers=False`
  in `migrations/env.py`, caught by running the full suite, not assumed.
- **P1-4 (frontend `AuditTrailPage` falsely claimed no backing API;
  audit/evidence/governance had no frontend client at all)** — added
  `frontend/src/api/audit.ts`, `evidence.ts`, `governance.ts` (following
  the exact existing `apiGet`/`apiPost` typed-client pattern), added the
  six missing TypeScript contract types (`MaskingPolicy`/`MaskingRule`,
  `MaskingPolicyVersion`, `PolicyApproval`, `BusinessConsumer`,
  `ConsumerDatasetRequest`, `AuditEvent`/`AuditEventType`,
  `AuditEvidencePackage`) to `frontend/src/api/types.ts`, and rewrote
  `AuditTrailPage.tsx` to actually call `GET /api/v1/audit/events` and
  render a real, filterable table instead of the stale placeholder.
  Proven by `AuditTrailPage.test.tsx` (real data rendered, honest empty
  state, and explicit assertions the old false claim no longer renders)
  plus a clean `npm run lint`/`npm run build`.
- **P1-5 (`ARCHITECTURE.md`'s observability claim was 100% unimplemented;
  `log_level` was dead code)** — added
  `control_plane.platform.logging_config` (real JSON structured logging,
  correlation-ID tagged, actually configured from `Settings.log_level`)
  and wired a request-logging middleware plus a scheduler job-event log
  line into `main.py`/`api/v1/lifecycle.py`. `ARCHITECTURE.md` section
  3.3 now honestly states what is real (structured logs + correlation
  IDs, control-plane only) versus what remains explicitly out of scope
  (real metrics/distributed tracing infrastructure, and an equivalent
  for data-plane/governance-service) rather than the prior blanket,
  false claim. Proven by `test_platform_logging.py` (7 tests, including
  a real HTTP request through `TestClient` producing a real JSON log
  line with the expected fields).
- **P1-6 (masking's per-source-system writers weren't atomic)** — every
  writer in `data_plane.masking.dataset_masker` (`mask_postgres_enrollment`,
  `mask_claims_parquet`, `mask_clinical_data_lake`, `mask_pbm_extract`,
  `mask_partner_lab_feed`) now writes to a temporary path and atomically
  renames it into place (`_atomic_write_via`/`_atomic_text_writer`) only
  on clean completion. Proven by
  `tests/masking/test_dataset_masker_atomic_writes.py` (7 tests): a real
  crash injected mid-write (via monkeypatching) into
  `mask_clinical_data_lake` -- the exact writer P1-6 named as its
  concrete example -- leaves no truncated file at its final path, either
  on a first write or (more operationally important) when overwriting a
  previous good run.
- **P1-7 (evidence-package checksum was unkeyed, weaker than the
  certification signature it could be embedded alongside)** — added
  `control_plane.platform.evidence_signing` (keyed HMAC-SHA256, same
  algorithm/canonicalization `data_plane.certification.signing` already
  used), upgraded `bundle_checksum_algorithm` from `"sha256"` to
  `"hmac-sha256"`, and wrote `docs/TAMPER_EVIDENCE_LIMITATIONS.md` as the
  one, canonical statement of the residual limitation neither mechanism
  solves (both are detection-only, both only as strong as their key's
  secrecy) -- referenced from both signing modules and
  `docs/COMPLIANCE_EVIDENCE.md` instead of each restating it separately.
  Proven by updated `test_evidence_repository.py` tests, including a new
  assertion that a checksum forged under the WRONG key is rejected
  (impossible to test meaningfully against the old unkeyed mechanism).
- **P1-8 (no enforced link between a registered `DatasetVersion` and
  Phase 10's governed, approved policy)** — added
  `POST /api/v1/lifecycle/dataset-versions/governed`, which independently
  re-derives (via `GovernanceRepository.get_approved_policy_version`,
  never trusting the certification report's own claim) whether the
  report's masking policy name/version match the currently-APPROVED
  `MaskingPolicyVersion`, rejecting with 409 if not. The pre-existing
  `POST /dataset-versions` is left unchanged but now explicitly
  documented as the ungoverned/direct path, per
  [ADR-0019](docs/adr/0019-governed-vs-ungoverned-dataset-version-registration.md)'s
  reasoning for why a breaking change to every pre-Phase-10 caller was
  rejected in favor of an additive, clearly-labeled second path. Proven
  by `test_lifecycle_governed_registration.py` (4 tests: the reproduction
  that the ungoverned path still allows an ungoverned registration by
  design, the governed path rejecting both "no approved policy exists"
  and "policy version mismatch," and the governed path succeeding and
  audit-tagging itself `governed: "true"` when the policy really is
  approved).
- **P1-9 (no distribution-shape verification anywhere in the pipeline)**
  — added a twelfth certification gate,
  `data_plane.certification.gates.check_distribution_shape` (new
  `CertificationGateType.DISTRIBUTION_SHAPE`), wired into
  `run_certification_pipeline` comparing `claim.billed_amount`'s value
  distribution between the real SUBSET-stage output and the real final
  (post-mask/optional-synthetic) output -- a real, lightweight
  gross-distortion sanity check (degenerate-collapse-to-zero, and an
  order-of-magnitude mean-ratio threshold), deliberately not a full
  statistical test suite, per its own docstring and
  `docs/CERTIFICATION_VS_MASKING.md`. Proven by five new gate unit tests
  (including a reproduction that a 1000x mean shift would have
  certified cleanly before this phase) plus the real pipeline
  integration test (`test_pipeline_against_real_estate.py`) now
  asserting twelve passing gates against a real estate run.
- **Documentation**: `THREAT_MODEL.md`, `SECURITY.md`, `ARCHITECTURE.md`
  section 3.3, `docs/COMPLIANCE_EVIDENCE.md`,
  `data_plane/certification/signing.py`'s docstring,
  `control_plane/platform/rbac.py`'s docstring, and
  `control_plane/db/models.py`'s docstring were all updated in place to
  describe the real, current mechanism rather than either the false
  pre-Phase-18A claim or a new claim overstating this phase's own,
  deliberately proportionate scope. Two new ADRs
  (`0018-minimal-jwt-identity-layer-for-rbac.md`,
  `0019-governed-vs-ungoverned-dataset-version-registration.md`).
- **Full test suite, run fresh (not assumed) at the end of this phase**:
  `libs/contracts` 62 passed, `services/control-plane` 236 passed,
  `services/data-plane` 451 passed, `services/governance-service` 2
  passed — **751 total Python tests passed, 0 failed**. `frontend`
  (Vitest) 40 passed across 11 files, `npm run lint` 0 errors, `npm run
  build` succeeds. No test was weakened, skipped, or deleted to make
  this phase's work "pass" — every count above is strictly additive over
  Phase 17's own 698 + 39 baseline.
- **All ten P0/P1 findings were deleted from `problems_final_review.md`**
  only after the evidence above was actually produced, per the phase
  prompt's explicit instruction. The thirteen P2 and ten P3 findings
  (23 total) are unchanged, left for Phase 18B.
- Left open, deliberately: every P2/P3 finding `problems_final_review.md`
  still lists (out of this phase's scope by design), plus the honestly
  narrower scope this phase's own fixes state explicitly -- P0-1's JWT
  layer is a minimal mechanism for a fixed set of demo identities, not a
  production IdP; P1-5's structured logging covers `services/control-plane`
  only, with no equivalent yet in `services/data-plane`/
  `services/governance-service` and no real metrics/tracing
  infrastructure anywhere; P1-7's keyed HMAC closes the "unkeyed, weaker
  than certification" inconsistency but not the inherent
  detection-not-prevention/key-colocation limitation
  `docs/TAMPER_EVIDENCE_LIMITATIONS.md` documents as out of scope without
  a real KMS/HSM integration.

## Phase 16 — what was actually delivered

- Audited the whole repository before writing anything, per
  `CONTRIBUTING.md`: `ARCHITECTURE.md`, all seventeen ADRs in `docs/adr/`,
  every `problems_phase_01.md`-`problems_phase_14.md` (specifically their
  still-open items, honest material for `failure-scenarios.md`/
  `tradeoffs.md`), `docs/tutorial/guide/` (the Phase 15 onboarding
  tutorial), `docs/CERTIFICATION_VS_MASKING.md`,
  `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`,
  `docs/CAPACITY_COST_TRADEOFFS.md`, `docs/COMPLIANCE_EVIDENCE.md`,
  `docs/SCALE_AND_PERFORMANCE.md`, `docs/PLATFORM_INTEGRITY.md`,
  `docs/runbooks/`, `docs/diagrams/`, `DATA_GOVERNANCE.md`, and
  `THREAT_MODEL.md` — this phase is a synthesis of what already exists,
  not new application code, so nothing below was written without first
  locating the real repository artifact it cites.
- Four new files in `docs/interview/`, split by concern rather than
  repeating the same content four times:
  - `docs/interview/system-design.md` — how a senior engineer would
    whiteboard the six planes and the nine-stage pipeline
    (`INGEST -> ... -> PUBLISH`), reusing/adapting the real
    `docs/diagrams/system-context.mmd`/`data-flow-sequence.mmd` diagrams
    and `ARCHITECTURE.md`'s own plane diagram rather than inventing new,
    inconsistent ones; answers "how do you preserve referential integrity
    while masking identifiers," "how do you prove masking completed
    correctly," "how do you prevent PHI from reaching lower
    environments," and "how do you produce audit evidence."
  - `docs/interview/tradeoffs.md` — the real, already-documented
    tradeoffs this repository made, each cited to the ADR and
    `problems_phase_NN.md` entries that actually recorded the decision:
    deterministic pseudonymization vs. true anonymization (ADR-0006),
    SQLite-locally/Postgres-portable (ADR-0004, `problems_phase_07.md`
    P7-1's real deferred-then-closed verification gap), checksum vs.
    HMAC vs. asymmetric signature for tamper-evidence
    (`data_plane.certification.signing`'s keyed HMAC vs.
    `control_plane.domain.evidence`'s unkeyed SHA-256 checksum, per
    ADR-0016 and `problems_phase_13.md` P13-2), shared immutable
    snapshots vs. per-environment copies (Phase 7's foreign-key
    architecture, Phase 8's real measured 80% savings), local-mode Spark
    vs. a real cluster (ADR-0017), and synthetic vs.
    masked-production-like data (Phase 5's `DataProvenance` tagging);
    also answers "when should you use synthetic data rather than masked
    data" and "how do you version masking policies" (ADR-0011's
    policy-version/engine-version split plus Phase 10's governed
    approval workflow).
  - `docs/interview/failure-scenarios.md` — Phase 11's eight real
    failure-injection scenarios and their real recovery mechanisms (the
    `_MASKING_RUN_INCOMPLETE.marker`, the dead-letter store, the
    retry/backoff helper's deliberately narrow scope, rollback/
    revocation), the real Phase 12 release-gate failure actually
    triggered and observed (CI run IDs, not a hypothetical), plus the
    explicit questions "how would you recover from a partially completed
    masking job" and "how do you handle schema drift" answered in full
    runbook-referencing depth.
  - `docs/interview/scaling.md` — the "500 TB estate," "50 teams," "avoid
    20 TB copies," and "how would Databricks/Spark fit" questions,
    grounded in Phase 8's real capacity planner and its real, configurable
    illustrative scenario, Phase 14's real local-mode Spark jobs and
    measured throughput numbers, and Phase 7's shared-immutable-snapshot
    architecture — explicit throughout about which numbers are real
    measurements, which are real aggregations of registered data, and
    which are illustrative models, and never claiming a distributed-
    cluster number that `docs/SCALE_AND_PERFORMANCE.md` itself says was
    never measured (only `local[*]` was).
- All twelve of the promptbook's required example questions are answered,
  each citing real repository paths — see the map above; none is answered
  only in the abstract.
- **No `problems_phase_16.md` was created.** Unlike every phase before it,
  `ROADMAP.md`'s own Phase 16 prompt does not ask for one, and this phase
  adds no new application code, no new test surface, and no new design
  decision of its own to record as an open problem — it is a citation
  layer over decisions and gaps every earlier phase already recorded in
  its own `problems_phase_NN.md`. Manufacturing a Phase 16 problems file
  would either duplicate those entries under a new ID or invent problems
  that don't exist; `problems_master.md` is unchanged by this phase for
  the same reason (nothing this phase built introduces a new open
  problem, and it resolves none of the existing ones, since it touches no
  code).
- This phase adds no new application code and therefore no new pytest
  test file. The full workspace suite was run, unmodified, to confirm
  writing documentation touched no application code path: `libs/contracts`
  62 passed, `services/control-plane` 195 passed, `services/data-plane`
  439 passed, `services/governance-service` 2 passed — 698 total,
  unchanged from `problems_phase_15.md`.
- Left open, inherited (not introduced) by this phase: every gap this
  phase's four files cite honestly (P0-3's missing storage adapter,
  P0-4's un-rendered diagrams, P2-2's untested free-text classification
  gap, P7-1/P7-2's scheduler-concurrency gap, P8-3's read-only vacuum
  candidates, P11-1's non-atomic per-file masking writes, P13-2's unkeyed
  evidence-bundle checksum, P14-1/P14-2/P14-5's Delta/skew/apples-to-
  apples gaps) remains exactly as open as its owning phase's problems
  file already describes it — this phase's job was to cite each
  accurately, not to close any of them.

## Phase 15 — what was actually delivered

- Audited `docs/tutorial/` and the whole repository before writing
  anything, per `CONTRIBUTING.md`: `docs/tutorial/` already contains
  `00-overview.md` plus numbered deep-dive chapters `01`-`09` and `13`
  (no `10`/`11`/`12`/`14` — those phases didn't add a chapter under
  this naming scheme), each an implementation-detail walkthrough
  assuming the reader already knows TDM/PHI/subsetting/masking
  vocabulary. This phase's own required chapter list (`ROADMAP.md`'s
  twenty topics) is a different, "zero to understanding the complete
  repository" arc that the existing chapters never build from first
  principles.
- **Filename/numbering decision** (recorded in full in
  `problems_phase_15.md`): grepped the whole repository for
  `docs/tutorial/0` and `docs/tutorial/1` first and found real
  cross-references from `ARCHITECTURE.md`, `CONTRIBUTING.md`, ADRs,
  `docs/diagrams/README.md`, `docs/PLATFORM_INTEGRITY.md`, a runbook,
  `README.md`, `problems_phase_04.md`/`05`/`07`, `scripts/README.md`,
  `services/control-plane/README.md`, and two data-plane package
  READMEs -- all pointing at the *existing* filenames, none at a
  `docs/tutorial/10`-`14` or `guide/` path. Renumbering or reusing any
  existing filename was therefore ruled out (it would break every one
  of those links); a new, non-colliding `docs/tutorial/guide/`
  subdirectory with its own `01`-`20` sequence (matching the
  promptbook's own chapter numbers exactly) was created instead.
- **Twenty new chapters** in `docs/tutorial/guide/`
  (`01-what-is-test-data-management.md` through
  `20-operating-tdm-as-a-product.md`) plus `docs/tutorial/guide/README.md`
  as the index -- each chapter teaches its concept from first
  principles for a junior data engineer with no prior TDM exposure,
  then links out to the matching existing `0X`/`13` chapter (or ADR/
  doc, where no numbered chapter exists for that topic -- platform
  integrity, CI/CD, cloud testing) for implementation depth, rather
  than duplicating that chapter's own worked examples. Every chapter
  points at real repository code; every captured "expected output"
  block was produced by actually running the named command in this
  environment (a fresh `tiny`-scale estate through discovery,
  subsetting, masking, and a full `--publish`ed certification run --
  11/11 gates passed -- plus a real `data_plane.capacity.cli footprint`
  measurement), not hand-typed. Chapters covering Phase 7/8/10
  behavior already demonstrated end-to-end with real captured output
  in the existing tutorial chapters quote that already-real output
  rather than re-running the same demo scripts a second time.
- Chapter 20 ("Operating TDM as a product") is an explicit synthesis,
  stated as such in the chapter itself: this repository never built a
  dedicated "product operations" module, so the chapter draws on real,
  already-built material across Phase 7 lifecycle/refresh, Phase 8
  capacity, Phase 10 governance, Phase 11 platform integrity, Phase 13
  audit evidence, and this repository's own `ROADMAP.md`/
  `CONTRIBUTING.md` process, rather than inventing an unbuilt
  capability.
- `docs/tutorial/00-overview.md`'s "Where to go next" section and
  `README.md`'s "Getting started" section both updated to point a new
  reader at `docs/tutorial/guide/README.md`, explicit that it is the
  onboarding path and the existing numbered chapters remain the
  implementation-depth reference.
- This phase adds no new application code, and therefore no new pytest
  test file -- `problems_phase_15.md` says so explicitly rather than
  fabricating a test against prose. The full workspace suite was run,
  unmodified, to confirm editing/adding documentation did not touch any
  application code path: `libs/contracts` 62 passed,
  `services/control-plane` 195 passed, `services/data-plane` 439
  passed, `services/governance-service` 2 passed -- 698 total,
  unchanged from `problems_phase_14.md`.
- Left open, tracked in `problems_phase_15.md`: no retroactive numbered
  `docs/tutorial/1X-...md` implementation-depth chapter was added for
  Phases 11/12/14 (out of this phase's 20-chapter-onboarding-arc scope;
  the new guide's Chapters 16-18 link to `docs/PLATFORM_INTEGRITY.md`/
  `docs/AZURE_PRODUCTION_DEPLOYMENT.md` directly instead) (P15-1);
  Chapter 20 is a synthesis across five phases, not a single module's
  documentation, and should not be read as evidence a unified
  "operate TDM as a product" capability already exists in code (P15-2);
  no Mermaid diagram this phase added has been rendered to a static
  image, consistent with the already-open `P0-4` (P15-3).

## Phase 14 — what was actually delivered

- Audited `services/data-plane` against this phase's own prerequisite
  before writing any code and confirmed a real, previously-documented
  gap: `pyspark`/`delta-spark` have been declared dependencies since
  Phase 0, but no file in `services/data-plane/src` had ever imported
  `pyspark` or built a `SparkSession` through Phase 13
  (`problems_phase_12.md`'s container-build note already said so).
- Two new, additive data-plane packages, mirroring `ADR-0013`'s
  Phase 8 plane-internal split:
  - `data_plane.spark` (`session.py`, `masking_job.py`,
    `subsetting_job.py`, `cli.py`) — real, runnable PySpark code.
    `run_claims_masking_job` masks the claims-warehouse `claim` table's
    `member_id`/`claim_id` columns with an Arrow-vectorized `pandas_udf`
    that reuses Phase 3's real `MaskingEngine` unmodified (proven
    byte-for-byte identical to the pandas engine's own output under the
    same key/scope). `run_member_subsetting_job` reimplements Phase 4's
    referential-closure concept (member selection -> claim -> claim
    line) as two explicit broadcast joins, never shuffling the large
    tables.
  - `data_plane.benchmarks` (`harness.py`, `report.py`, `cli.py`) — a
    real measurement harness reusing every underlying Phase 1/3/4/8/14
    engine it measures (never reimplementing masking/subsetting/
    footprint logic a second time): records/sec, masking throughput
    (pandas vs. Spark), subsetting throughput (pandas vs. Spark),
    dataset generation time, validation time, storage footprint, and
    Parquet compression ratio, run against a real, freshly generated
    estate at a caller-selected `data_plane.reference_data.scale.
    ScaleProfile`.
- Two real, previously-undocumented local-mode PySpark-on-Windows
  failure modes found and fixed while implementing this phase (not
  hypothetical — both reproduced in this repository's own development
  environment): a native `winutils.exe`/`HADOOP_HOME` shim requirement
  for local file writes (`scripts/setup_local_spark_windows.py` +
  `data_plane.spark.session.configure_windows_hadoop_runtime`), and a
  Python-worker crash (`SparkException: Python worker exited
  unexpectedly`, no Python traceback) caused by the JVM launching a
  different `python` on `PATH` than the interpreter that built the
  session, fixed by `pin_worker_python_interpreter` pinning
  `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` to `sys.executable`.
- [ADR-0017](docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md):
  why this tooling lives inside `services/data-plane` rather than a new
  service, why "real PySpark" means `local[*]` only (no Spark cluster
  exists in `infra/`), which two operations were chosen for a real
  Spark reimplementation and why, and why no real Delta Lake write is
  executed this phase.
- `docs/SCALE_AND_PERFORMANCE.md`: real benchmark numbers from real runs
  at `qa` scale (81,295 rows; 10,726 claims) and `performance` scale
  (766,252 rows; 105,936 claims) — including the measured finding that
  Spark's masking throughput went from 1,707 records/sec at `qa` scale
  to 12,714 records/sec at `performance` scale (fixed per-job overhead
  amortizing over ~10x more rows), real captured `df.explain()` output
  proving predicate pushdown (`PushedFilters`) and broadcast joins
  (`BroadcastHashJoin`) actually occurred, and a real reproduction of
  the small-file problem (200 output files at Spark's cluster-tuned
  default shuffle-partition count vs. 8 files at this package's
  laptop-appropriate default, for the same 30,030-row input) — plus
  honest documentation of what is conceptual rather than measured (data
  skew, Delta Lake optimization concepts, autoscaling) and why.
- 26 new tests: `services/data-plane/tests/spark/` (17 — real Spark
  sessions, real on-disk Parquet, a real cross-validation that the
  Spark `pandas_udf` and the pandas `MaskingEngine` produce identical
  tokens, Windows-hadoop-runtime-resolution logic exercised via
  monkeypatched `sys.platform`) and
  `services/data-plane/tests/benchmarks/` (9 — every `benchmark_*`
  function and the full `run_full_suite` pipeline, against a real
  `tiny`-scale estate). Full workspace suite after this phase:
  `libs/contracts` 62 passed, `services/control-plane` 195 passed,
  `services/data-plane` 439 passed (413 before this phase + 26 new),
  `services/governance-service` 2 passed — no regressions.
- Left genuinely open, tracked in `problems_phase_14.md`: no real Delta
  Lake table is written anywhere in this repository yet (P14-1); skew
  is documented but not reproduced from real measurement (P14-2);
  autoscaling is not applicable to `local[*]` and is documented
  conceptually only (P14-3); neither new Spark job is wired into the
  control plane's job orchestrator (P14-4, the same gap `ARCHITECTURE.md`'s
  Phase 3/4 notes already document for the pandas-engine versions);
  `run_claims_masking_job` masks only two columns of one table, not
  Phase 3's full masking policy, so the pandas-vs-Spark masking
  comparison in `docs/SCALE_AND_PERFORMANCE.md` is not a pure
  apples-to-apples race (P14-5); and the two Windows-local-mode fixes
  are only exercised for real on Windows, never on this repository's own
  Linux CI (P14-6).

## Phase 13 — what was actually delivered

- Audited Phase 11's existing audit log (`control_plane.platform.audit`)
  against this phase's exact requirement list before writing any new
  code, and found two genuine, narrow gaps rather than reinventing the
  mechanism: (1) `AuditEventType.ACCESS_GRANTED`/`ACCESS_REQUESTED` had
  existed since Phase 0 but were never wired to anything, and nothing
  recorded "who accessed a provisioned dataset version" specifically;
  (2) `LifecycleRepository.refresh()`/`rollback()` each returned only
  the single record they had just created -- there was no read method
  or endpoint to list refresh/rollback history after the fact.
- Two new `AuditEventType` values
  (`healthcare_tdm_contracts.audit`): `DATASET_VERSION_ACCESSED` and
  `EVIDENCE_PACKAGE_GENERATED`.
- A new, real mutation closing gap (1):
  `POST /api/v1/lifecycle/dataset-versions/{version_id}/access`
  (`control_plane.api.v1.lifecycle.record_dataset_version_access`) --
  checks the version exists, then appends a real
  `DATASET_VERSION_ACCESSED` audit event.
- Two new read methods/endpoints closing gap (2):
  `LifecycleRepository.list_refresh_runs`/`list_rollback_events`
  (`services/control-plane/src/control_plane/domain/lifecycle/repository.py`),
  exposed at `GET /api/v1/lifecycle/refresh-runs` and
  `GET /api/v1/lifecycle/rollback-events`.
- A new contract, `healthcare_tdm_contracts.evidence.AuditEvidencePackage`
  (plus its `COMPLIANCE_DISCLAIMER` constant), and a new control-plane
  domain, `control_plane.domain.evidence.EvidenceRepository`
  (`build_evidence_package`, `compute_bundle_checksum`,
  `verify_bundle_checksum`) -- a real aggregation (not a
  reimplementation) of the dataset manifest (Phase 7), classification
  summary (Phase 2), masking policy version + approvals (Phase 10),
  provisioning/refresh/rollback/revocation history (Phase 7), and the
  relevant audit trail (Phase 11), joined in one `sqlalchemy.orm.Session`,
  plus a real SHA-256 bundle checksum and (only when the caller supplies
  them) the caller's own Phase 6 `CertificationReport`/Phase 4
  `SubsetManifest` embedded verbatim and used to derive
  `integrity_report`/`quality_report`. Exposed at
  `POST /api/v1/evidence/dataset-versions/{version_id}/package`
  (`control_plane.api.v1.evidence`).
- [ADR-0016](docs/adr/0016-audit-evidence-lives-in-control-plane.md):
  why this aggregation lives in `services/control-plane`, mirroring
  ADR-0014/ADR-0015's reasoning.
- `docs/COMPLIANCE_EVIDENCE.md`: the honest explanation of what the
  Audit Evidence Package does and does not claim -- it supports an
  organization's own privacy/security/compliance program; it is not
  itself a HIPAA (or any other regulatory) certification, attestation,
  or guarantee. `ARCHITECTURE.md` section 2.4 updated to point here.
- `docs/tutorial/13-auditability-and-compliance-evidence.md`.
- New tests: `libs/contracts/tests/test_evidence_contract.py` (3),
  `services/control-plane/tests/test_evidence_repository.py` (15),
  `services/control-plane/tests/test_evidence_api.py` (3), plus
  additions to `test_lifecycle_repository.py` (2),
  `test_lifecycle_api.py` (3), and `test_platform_audit.py` (1) for the
  new read methods/endpoints and event types -- all against real
  SQLite-backed repositories and real HTTP requests, no mocking of the
  database layer, per `CONTRIBUTING.md`'s data-quality-test convention.
  Full workspace suite after this phase: `libs/contracts` 62 passed,
  `services/control-plane` 195 passed, `services/data-plane` 413
  passed, `services/governance-service` 2 passed -- no regressions.
- Left genuinely open, tracked in `problems_phase_13.md`: the Audit
  Evidence Package can only embed a real `CertificationReport`/
  `SubsetManifest` if the caller supplies it (control-plane still does
  not durably store either); the bundle checksum is a SHA-256 integrity
  check, not a keyed-HMAC non-repudiation signature; the new endpoints
  this phase adds are not RBAC-gated; and the audit-trail aggregation
  only finds events under known subject ids.

## Phase 12 — what was actually delivered

- Six real GitHub Actions workflows (`.github/workflows/`):
  `ci.yml` (rewritten from Phase 0's untested skeleton --
  `lint-python`, `typecheck-python`, a per-package `unit-tests` matrix,
  a real-Postgres-backed `integration-tests` job, `data-quality-tests`
  (masking/referential-integrity/certification-gate suites named as
  distinct steps), `security-checks` (secrets scan + `pip-audit`),
  `frontend-lint`/`frontend-build`/`frontend-unit-tests`, and a
  `release-gate` job that fails if any required job did not succeed),
  `container-build.yml` (builds + smoke-tests + Trivy-scans the three
  new images, no registry push), `e2e.yml` (real Playwright run against
  a real control-plane + real Vite dev server, per
  `frontend/playwright.config.ts`'s own documented startup sequence),
  and `deploy-qa.yml` -> `deploy-staging-uat.yml` -> `deploy-production.yml`
  (chained via real `workflow_run` dependencies + GitHub Environments,
  each deploying a Docker Compose stand-in with real health checks --
  explicitly documented as not a real cloud target; see
  `docs/AZURE_PRODUCTION_DEPLOYMENT.md`)
- Real, minimal, multi-stage Dockerfiles for the three services with
  actual runnable code (`services/control-plane/Dockerfile`,
  `services/governance-service/Dockerfile`, `frontend/Dockerfile` +
  `nginx.conf`) -- `data-plane` deliberately excluded (batch/CLI
  toolkit, no `SparkSession` created anywhere yet; see
  `problems_phase_12.md`'s decision record)
- `governance_service/main.py` + `api/health.py`: this service's first
  real code (a liveness endpoint only, mirroring exactly how
  `control_plane.main` looked in Phase 0), added so it has something
  real to containerize/deploy; its RBAC/audit/secrets/evidence-store
  responsibilities (`ARCHITECTURE.md` section 2.4) remain unbuilt
- `infra/docker/docker-compose.yml` extended with real `control-plane`/
  `governance-service`/`frontend` containers (built from the
  Dockerfiles above) alongside the existing `postgres`/`minio`, with
  real health checks and overridable host ports -- **verified end to
  end against a real Postgres container**: `GET /api/v1/ready` reports
  the database check healthy/reachable, resolving the "Postgres never
  verified against real application code" gap `ARCHITECTURE.md`'s own
  Phase 7/8/11 notes and `problems_master.md` P0-2 had flagged since
  Phase 0/7
- `infra/k8s/helm/tdm-platform/templates/`: real Deployment/Service
  manifests for all three containerized services, a ConfigMap/Secret
  split for control-plane configuration, and a disabled-by-default
  Ingress -- `helm lint`/`helm template` both verified clean
- `infra/terraform/azure/main.tf`: a real, `terraform fmt`/`validate`-clean
  example (AKS, Azure Database for PostgreSQL Flexible Server, an ADLS
  Gen2 Storage Account, Azure Container Registry, Key Vault, and the
  role assignments between them) -- never applied against a real
  subscription; `infra/terraform/aws/main.tf` kept as the lighter,
  structural cloud-portable counterpart
- `docs/AZURE_PRODUCTION_DEPLOYMENT.md`: the Azure-oriented production
  deployment narrative `ROADMAP.md` asks for, explicit throughout about
  what is genuinely Azure-specific versus what the existing
  plane-separation/storage-adapter architecture (ADR-0003, ADR-0005)
  keeps portable -- including an honest statement that the storage-adapter
  interface itself remains unimplemented (`problems_master.md` P0-3,
  still open), so Azure Blob/ADLS is provisioned as a real Terraform
  target but not yet written to by any real job
- A real, deliberate release-gate failure experiment (a genuinely
  broken test pushed to a scratch branch, observed failing and blocking
  in the Actions UI, then reverted) proving `ROADMAP.md`'s release-gate
  requirement ("a release must fail if unit/integration/masking/
  referential-integrity tests fail, or critical security validation
  fails") is real, not just written -- see `problems_phase_12.md` for
  the run IDs/URLs
- Two real, incidental fixes found while wiring CI for the first time
  (per `problems_master.md` P0-2's own prediction that this had never
  actually been exercised): a ruff lint failure (unused imports/local
  variable, three files, present since Phases 3/8/11) and a real mypy
  strict-mode bug (`control_plane.platform.audit`, a `str`/`UUID`
  mismatch invisible to every existing test) -- both fixed, both now
  hard-blocking CI gates; `services/data-plane`'s 15 pre-existing
  strict-mode mypy findings are reported but left open and
  non-blocking, explicitly out of this phase's scope (see
  `problems_phase_12.md`)
- One new test (`services/governance-service/tests/test_health_api.py`);
  every other Python package's test count is unchanged --
  `libs/contracts` 59, `services/control-plane` 171,
  `services/data-plane` 413, `services/governance-service` 2 (was 1),
  **645 total, all passing** -- see `problems_phase_12.md` for what's
  still open

## Phase 11 — what was actually delivered

- `docs/PLATFORM_INTEGRITY.md`: an honest, control-by-control account
  of every Phase 11 requirement -- which were already real from
  earlier phases (certification's state machine/HMAC signing,
  Phase 7's rollback/revocation, Phase 10's approved-policy-only
  consumer requests, Phase 3's masking idempotency and secret-missing
  handling), which are genuinely new here, and which remain
  documented, honest gaps
- `control_plane.platform` (new package,
  `services/control-plane/src/control_plane/platform/`), living here
  rather than `services/governance-service` for the same
  same-transaction reasons ADR-0014 gives for Phase 10's governance
  domain -- see
  [ADR-0015](docs/adr/0015-platform-integrity-controls-in-control-plane.md):
  - `rbac.py` -- a real, enforced authorization check (`Role`,
    `Permission`, `authorize()`), gating `POST /dataset-versions/{id}/revoke`,
    `.../rollback`, and `POST /policy-versions/{id}/approve`/`.../reject`
    -- proven by a real HTTP 403 for an under-privileged actor, not a
    no-op
  - `audit.py` -- `AuditLogRepository`, the first real, DB-backed
    wiring of the Phase 0 `healthcare_tdm_contracts.AuditEvent`
    contract (new `audit_event` table, append-only by construction --
    no update/delete method exists), wired into every real Phase 7/10
    mutation this phase touches, exposed read-only at
    `GET /api/v1/audit/events`
  - `readiness.py` -- `/api/v1/ready`, the dependency-aware check
    Phase 0's own `/health` docstring promised ("added once this
    service has real dependencies to check"), checking real lifecycle
    database connectivity (required) and catalog artifact presence
    (informational)
  - `retry.py` -- a small, generic, tested retry-with-backoff helper,
    wired into the readiness database check only (deliberately not
    into data-plane job execution -- see below)
  - `dead_letter.py` -- `DeadLetterStore` (new `dead_letter_event`
    table), wired into `LocalRefreshOrchestrator.run_due_refreshes`'s
    existing per-request failure isolation so a failed scheduled
    refresh is now durably recorded, not only returned to one caller
- `control_plane.config.Settings` gained real `field_validator`s
  (log level, API prefix, database URL shape, CORS origin scheme) --
  previously every field had a type but no value validation
- `LifecycleRepository.register_dataset_version` is now idempotent per
  `certification_report_id` -- a real duplicate-row bug found while
  writing this phase's job-idempotency test, fixed
- `data_plane.masking.dataset_masker.mask_estate` now writes a
  `_MASKING_RUN_INCOMPLETE.marker` at the start of a run and removes it
  only on clean completion -- a real gap found (no on-disk signal that
  a masking run crashed partway through) and a real, though partial,
  fix (`is_masking_run_complete()`); the honest remaining limit
  (per-file writes still not atomic) is `problems_phase_11.md` P11-1
- `scripts/security/detect_secrets.py`: a repo-wide secret-detection
  scan generalizing Phase 3's scoped "no secrets committed" test
  (bare 64-hex-char strings, AWS access key IDs, PEM private key
  headers, known secret-shaped env vars, a conservative generic
  assigned-secret pattern), verified clean against this repository's
  real tracked tree
- `scripts/security/dependency_scan.py`: a real `pip-audit` hook
  across every workspace package, reporting an explicit failure (never
  a silent pass) when `pip-audit` is unavailable -- not yet wired into
  CI (Phase 12's job)
- New ADR: [ADR-0015](docs/adr/0015-platform-integrity-controls-in-control-plane.md)
  (where these controls live, and why RBAC is enforced at the API
  layer rather than the domain-repository layer)
- Three new runbooks (`docs/runbooks/backup-and-restore.md`,
  `masking-job-failure-recovery.md`,
  `duplicate-requests-and-revoked-datasets.md`), each REAL (not
  aspirational) and cross-referencing the exact tests that back them
- Eight real failure-injection tests (masking job crashes halfway,
  source schema changes, storage unavailable, duplicate refresh
  request, certification validation fails, secret missing, dataset
  becomes corrupted, consumer requests revoked dataset), split across
  `services/data-plane/tests/platform_integrity/test_failure_injection.py`
  (the four data-plane-owned scenarios) and
  `services/control-plane/tests/test_failure_injection.py` (the four
  control-plane-owned scenarios) -- each either genuinely new, or an
  explicit, real extension of an existing Phase 3/6/7 test, documented
  either way rather than presented as uniformly new
- `libs/contracts`: `AuditEventType` extended with seven new values
  (`DATASET_VERSION_REGISTERED`, `DATASET_VERSION_REVOKED`,
  `DATASET_VERSION_ROLLED_BACK`, `ENVIRONMENT_REQUEST_CREATED`,
  `REFRESH_EXECUTED`, `CONSUMER_REQUEST_SUBMITTED`,
  `CONSUMER_REQUEST_FULFILLED`, `POLICY_REJECTED`) -- the existing
  Phase 0 vocabulary (written for the certification/classification
  domain) did not have precise-enough values for this phase's real
  lifecycle/governance events
- 55 new tests (17 in `services/data-plane`'s new
  `tests/platform_integrity/`; 38 in `services/control-plane`'s new
  `test_platform_rbac.py`/`test_platform_audit.py`/
  `test_platform_readiness.py`/`test_platform_retry.py`/
  `test_config_validation.py`/`test_failure_injection.py`), plus
  updates to existing Phase 7/8/10 tests and demo scripts to carry the
  new required `actor_role` field on the four newly RBAC-gated
  endpoints; `services/control-plane` is now 171 tests total, all
  passing, and `services/data-plane`'s pre-existing 396 tests continue
  to pass unmodified (413 total) -- see `problems_phase_11.md` for
  what's still open

## Phase 10 — what was actually delivered

- A real, database-backed centralized masking governance domain
  (`control_plane.domain.governance`, tables added to the same
  `control_plane.db.models` schema Phase 7 defined): `MaskingPolicyVersion`
  (a governed, immutable snapshot of a real Phase 3 `MaskingPolicy`),
  `PolicyApproval` (an append-only approval-decision log), enforced as a
  real five-state (`draft`/`pending_approval`/`approved`/`rejected`/
  `superseded`) state machine (`control_plane.domain.governance.state_machine`),
  mirroring the exact split `data_plane.certification.state_machine`
  (Phase 6) and `control_plane.domain.lifecycle.state_machine` (Phase 7)
  already established
- `BusinessConsumer` (two real seeded rows, `LEFT_ARM`/`RIGHT_ARM`) and
  `ConsumerDatasetRequest` -- a consumer's request for a dataset into an
  environment with its own subset-size hint/refresh cadence/performance
  requirements, referencing an APPROVED `MaskingPolicyVersion` by
  foreign key only; no field on the model or parameter on
  `GovernanceRepository.submit_consumer_request` can carry a masking
  rule, enforced both structurally and by a real
  `PolicyVersionNotApprovedError` rejection
- `GovernanceRepository.fulfill_consumer_request`: the real integration
  point -- calls directly into the unmodified Phase 7
  `LifecycleRepository` (same `Session`, same transaction) to produce a
  real `EnvironmentDatasetRequest`, which Phase 8's unmodified
  `CapacityPlanner` picks up with zero governance-specific capacity code
- New `libs/contracts` module `governance.py`:
  `MaskingPolicyVersion`, `PolicyApproval`, `PolicyApprovalStatus`,
  `POLICY_APPROVAL_STATUS_TRANSITIONS`, `BusinessConsumer`,
  `ConsumerDatasetRequest`, `ConsumerRequestStatus` -- named
  `ConsumerDatasetRequest` rather than `DatasetRequest` specifically to
  avoid colliding with Phase 7's `EnvironmentDatasetRequest`
- New FastAPI router `control_plane/api/v1/governance.py`
  (`/api/v1/governance/*`): policy-version draft/submit/approve/reject/
  list/get, approval history, business-consumer register/list/get,
  consumer-request submit/fulfill/list/get
- [ADR-0014](docs/adr/0014-masking-governance-lives-in-control-plane.md):
  why this domain lives in `services/control-plane` rather than
  `services/governance-service` (a structural scaffold with no database
  or FastAPI app as of this phase) -- the same-transaction integration
  with Phase 7/8 was the deciding factor
- `scripts/demo_phase10_governance.py`: end-to-end, real (not mocked)
  demonstration -- drafts/approves the real Phase 3 `DEFAULT_POLICY` as
  a governed policy version, registers LEFT_ARM/RIGHT_ARM, runs TWO real
  Phase 6 certification pipelines (different subset sizes, the exact
  same governed policy object) to produce two real `DatasetVersion`s,
  has both arms submit and fulfill `ConsumerDatasetRequest`s referencing
  the identical `policy_version_id`, has RIGHT_ARM request additional QA
  capacity with its own refresh cadence (shown flowing into a real
  Phase 7 `EnvironmentDatasetRequest` and a real Phase 8 capacity-plan
  before/after), and demonstrates a rejected adversarial bypass attempt
  (HTTP 409) against an unapproved policy version
- `docs/tutorial/09-centralized-masking-governance.md`
- 18 new Python tests (`test_governance_repository.py`,
  `test_governance_api.py`), including
  `test_left_arm_and_right_arm_resolve_to_same_approved_policy_version`
  and `test_consumer_cannot_attach_custom_masking_rules`;
  `services/control-plane` is now 115 tests total, all passing

## Phase 9 — what was actually delivered

- A real, running React + TypeScript + Vite console
  (`frontend/`, real `npm install` -- 435 packages, real
  `npm run build`/`npm run lint`/`npm run test` all passing): fourteen
  route-mounted pages plus a composed Dataset Detail page, per
  `frontend/src/pages/README.md`'s table -- Dashboard, Data Sources,
  Data Catalog, Sensitive Data Discovery, Masking Policies, Subsetting
  Jobs, Synthetic Data, Certification, Datasets (+ Detail), Environment
  Provisioning, Refresh Calendar, Capacity & Cost, Audit Trail, Platform
  Health
- A typed API client layer (`frontend/src/api/`): a small `fetch`
  wrapper (`client.ts`, real `ApiError` with HTTP status/detail),
  hand-maintained strict TypeScript interfaces mirroring every
  `libs/contracts` Pydantic model this console touches (`types.ts`), and
  one domain module per control-plane router (`catalog.ts`,
  `lifecycle.ts`, `capacity.ts`, `masking.ts`, `subsetting.ts`,
  `synthetic.ts`, `certification.ts`, `health.ts`) -- pages never call
  `fetch` directly
- Four new, real, read-only control-plane endpoints
  (`services/control-plane/src/control_plane/api/v1/masking.py`,
  `subsetting.py`, `synthetic.py`, `certification.py`) backed by a new
  `control_plane/artifacts/` package, following ADR-0009's exact
  JSON-artifact-handoff pattern to expose Phases 3/4/5/6's real,
  already-working engines (which previously only wrote a JSON artifact
  to disk) -- see `ARCHITECTURE.md`'s Phase 9 note and
  `problems_phase_09.md` for the per-page build-vs-placeholder decision
  record
- A real Dataset Detail page composing FOUR real endpoints (lifecycle +
  the three new Phase 9 artifact endpoints) into one view -- lineage,
  masking policy, subset policy, dataset version, certification, row
  counts, referential-integrity status (from the certification report's
  own gate result), storage footprint, and consumer environments -- see
  `frontend/src/pages/DatasetDetailPage.tsx`'s module docstring for the
  exact composition and why no single endpoint has it all
  - a small, deliberate CORS addition
  (`TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS`,
  `services/control-plane/src/control_plane/config.py`,
  `main.py`) -- opt-in, empty (no CORS middleware installed) by
  default, matching ADR-0008's same-origin-via-dev-proxy default; only
  activates for the documented `VITE_API_BASE_URL` escape hatch or a
  future non-proxied deployment
- Vitest + React Testing Library component tests (39 tests across 11
  files: `StatusBadge`, `DataTable`, `StatCard`, `ErrorState`,
  `NotYetAvailable`, `AsyncSection`, `format.ts` utilities, the typed
  API client, `DashboardPage`, `PlatformHealthPage`, `AuditTrailPage`)
  -- including a real bug caught and fixed by the tests themselves:
  `formatBytes`'s original `Math.log10`-based implementation
  mis-formatted exact powers of 1000 (a real IEEE-754 floating-point
  quirk, `Math.log10(1000) === 2.9999999999999996` in JS)
- Playwright E2E tests (`frontend/e2e/`, 6 tests across 3 spec files)
  for the three required critical workflows -- Dashboard with real
  data, Data Catalog with real classifications (plus category
  filtering), and Dataset Detail (lineage/masking policy/certification/
  etc.) -- run against the REAL control plane and REAL Vite dev server
  (no mock server), executed and passing in this environment; see
  `frontend/playwright.config.ts`'s header comment for the two-server
  startup sequence and `problems_phase_09.md` for an environment quirk
  encountered and worked around during verification
- `scripts/demo_phase9_console_data.py`: generates real end-to-end demo
  data (two real certification pipeline runs, one with synthetic
  scenarios, both registered as dataset versions and requested into all
  five environments) at the control plane's *default* settings paths,
  so `uvicorn control_plane.main:app` run with zero configuration
  serves real data for manual exploration or the Playwright suite
- Extended `libs/contracts`: none -- Phase 9 reused every existing
  contract shape unmodified (`SubsetManifest`,
  `SyntheticGenerationManifest`, `CertificationReport`, `CatalogEntry`,
  `DatasetVersion`, `EnvironmentDatasetRequest`, the capacity shapes);
  only `services/control-plane`'s own artifact repositories and one
  new control-plane-local `MaskingRunSummary` mirror type were added
- 14 new Python tests (`services/control-plane`'s new
  `test_masking_api.py`, `test_subsetting_api.py`,
  `test_synthetic_api.py`, `test_certification_api.py`) plus 5 new CORS
  tests (`test_cors.py`); `services/control-plane` is now 97 tests
  total, and `services/data-plane`'s/`libs/contracts`' pre-existing
  test suites continue to pass unmodified -- see `problems_phase_09.md`
  for what's still open

## Phase 8 — what was actually delivered

- Capacity planning split across two new, additive modules, per
  [ADR-0013](docs/adr/0013-capacity-planning-plane-split.md): real,
  on-disk footprint measurement
  (`services/data-plane/src/data_plane/capacity/`) and real, DB-backed
  capacity aggregation over Phase 7's existing lifecycle schema
  (`services/control-plane/src/control_plane/domain/capacity/`) --
  neither re-solves Phase 7's "avoid unnecessary duplicate physical
  copies" requirement; together they quantify the savings that
  architecture already produces
- `CapacityPlanner`
  (`control_plane.domain.capacity.planner.CapacityPlanner`): real,
  DB-backed `dataset_version_footprint`, `environment_capacity_demand`,
  `capacity_plan` (the concrete naive-vs-shared storage comparison --
  what every `EnvironmentDatasetRequest` would cost with an independent
  physical copy vs. what Phase 7's real shared-immutable-snapshot
  architecture actually costs, both computed from real registered
  `DatasetVersion.size_bytes`), and `vacuum_candidates` (a real,
  live-computed query for expired/revoked/rolled-back versions
  referenced by zero environments -- read-only, see `problems_phase_08.md`
  P8-3), plus a pure `illustrative_capacity_plan` function implementing
  `ROADMAP.md`'s own "Production: 100 TB, QA 10%, SIT 5%, UAT 15%"
  example as a real, runnable, configurable model (extended honestly to
  DEV and PERFORMANCE -- PERFORMANCE modeled at 100% in its own share
  tier, since subsetting would undermine the validity of the tests it's
  meant to run; see `docs/CAPACITY_COST_TRADEOFFS.md` section 4)
- Real, measured Parquet-vs-CSV compression numbers from actual Phase
  1/6 output, demonstrated end to end
  (`data_plane.capacity.footprint.measure_parquet_compression`,
  `scripts/demo_phase8_capacity.py`) -- and an honest, scale-dependent
  finding, not a fabricated constant: at `tiny` scale (a handful of rows
  per file) Parquet's real, measured footer/statistics overhead can
  exceed its compression benefit (overall ratio ~0.52x, i.e. *larger*
  than CSV), while `developer` scale measured ~1.43x and `qa` scale
  measured ~3.7x -- see `docs/CAPACITY_COST_TRADEOFFS.md` section 2 and
  `services/data-plane/tests/capacity/test_footprint.py`
- Real, on-disk Hive-style partition analysis
  (`data_plane.capacity.partitioning.analyze_partitions`), run against
  the real `batch=...` partitions
  `data_plane.reference_data.writers.parquet_writer` already writes --
  analysis of existing real partitioning, not new infrastructure
- A modeled (explicitly not measured) incremental-refresh savings
  illustration (`data_plane.capacity.incremental.estimate_incremental_savings`)
  and a documented copy-on-write/vacuum concept mapping onto Phase 7's
  real refresh-repointing and this phase's real `vacuum_candidates`
  mechanisms -- honestly scoped as design documentation plus real
  arithmetic over real data, never presented as unbuilt infrastructure
  that exists (`docs/CAPACITY_COST_TRADEOFFS.md` sections 6-7)
- Extended `libs/contracts`: `CompressionMeasurement`,
  `FootprintMeasurementReport`, `PartitionSummary`,
  `DatasetVersionFootprint`, `EnvironmentCapacityDemand`, `CapacityPlan`,
  `VacuumCandidate`, `EnvironmentCapacityRequirement`,
  `IllustrativeCapacityScenario`, `IllustrativeCapacityPlan`,
  `IncrementalRefreshEstimate`
  (`libs/contracts/src/healthcare_tdm_contracts/capacity.py`)
- 7 new FastAPI endpoints under `/api/v1/capacity` (dataset-version
  footprint, environment-request demand, aggregate plan, vacuum
  candidates, illustrative plan GET/POST), reusing Phase 7's existing
  `get_db_session` dependency rather than duplicating session wiring
- `docs/CAPACITY_COST_TRADEOFFS.md`: an honest account of which numbers
  are real measurements, which are real aggregations of already-
  registered data, and which are configurable illustrations -- including
  the real, scale-dependent compression finding above and why
  subsetting/masking's realism tradeoffs are real costs, not just
  storage savings
- 54 new tests (18 in `services/data-plane`'s new `tests/capacity/`
  suite -- against a real generated estate, not mocks; 12 + 11 = 23 in
  `services/control-plane`'s new `test_capacity_planner.py`/
  `test_capacity_api.py`; 13 in `libs/contracts`'s new
  `test_capacity_contract.py`); `libs/contracts` is now 59 tests total,
  `services/control-plane` 78 total, `services/data-plane`'s pre-existing
  378 tests continue to pass unmodified with 18 more added (396 total)
  -- see `problems_phase_08.md` for what's still open

## Phase 7 — what was actually delivered

- The control plane's first real, database-backed domain model
  (`services/control-plane/src/control_plane/db/models.py`,
  `control_plane/domain/lifecycle/`) -- every prior control-plane
  capability (the Phase 2 catalog) was a read-only view over a JSON
  artifact another plane produced; this phase's tables (dataset
  versions, refresh policies, environment dataset requests, refresh
  runs, rollback events) are the metadata plane's first real
  persistent, queryable state, per `ARCHITECTURE.md` section 2.3 and
  [ADR-0004](docs/adr/0004-postgresql-metadata-store.md) -- SQLite
  locally (zero infrastructure, same Phase 1 pattern), Postgres-portable
  by construction (no `JSONB`, no native `UUID` columns, mirroring
  `data_plane.reference_data.postgres_models`)
- `DatasetVersion` registered directly from a real Phase 6
  `CertificationReport` (`CERTIFIED`/`PUBLISHED` only, enforced), and
  `EnvironmentDatasetRequest` as a *separate*, per-environment pointer
  to it -- the concrete mechanism behind "avoid unnecessary duplicate
  physical copies": many environments reference one `storage_uri` via
  foreign key, never a copy, verified end to end against two real
  certification pipeline runs
  (`scripts/demo_phase7_lifecycle.py`, all 5 example environments
  sharing one dataset version's storage location)
- All five example environments' refresh cadences (DEV/QA weekly, SIT
  biweekly, UAT release-driven, PERFORMANCE monthly/on-demand), fully
  runtime-configurable via `PUT /api/v1/lifecycle/refresh-policies`
  (never hardcoded), with correct `next_refresh_at` computation
  demonstrated for every one of the five in a real run
  (`control_plane/domain/lifecycle/cadence.py`)
- A real, enforced `DatasetVersionStatus` lifecycle (`ACTIVE` ->
  `EXPIRED`/`REVOKED`/`ROLLED_BACK`; `ROLLED_BACK` -> `ACTIVE`/`REVOKED`;
  `EXPIRED` -> `REVOKED`), mirroring Phase 6's
  `CertificationStatus`/`state_machine` split
  (`control_plane/domain/lifecycle/state_machine.py`) -- an invalid
  transition (e.g. revoking an already-revoked version) is rejected by
  code, not merely documented, and covered by adversarial tests
- Real rollback (`POST /environment-requests/{id}/rollback`) and
  revocation (`POST /dataset-versions/{id}/revoke`) demonstrated end to
  end against real data, including the documented, deliberate decision
  that revocation never silently migrates an environment already using
  the revoked version (visibility over automation -- see
  `docs/tutorial/07-dataset-lifecycle-and-refresh.md`) while still
  blocking that version from being newly *selected* by any future
  request/refresh/rollback
- `RefreshOrchestrator` (`control_plane/domain/lifecycle/scheduler.py`):
  a two-method orchestration abstraction (`due_refreshes`,
  `run_due_refreshes`) with a real, tested `LocalRefreshOrchestrator`
  implementation and a documented (not faked) seam for a future Airflow
  DAG, Databricks Workflow, or cloud scheduler to plug into --
  [ADR-0012](docs/adr/0012-refresh-orchestration-abstraction.md)
- Extended `libs/contracts`:
  `Environment`, `RefreshCadenceType`, `DatasetVersionStatus`,
  `DATASET_VERSION_STATUS_TRANSITIONS`, `DatasetVersion`,
  `RefreshPolicy`, `EnvironmentDatasetRequest`, `RefreshRunRecord`,
  `RollbackRecord`, `RefreshTrigger`, `EnvironmentRequestStatus`
  (`libs/contracts/src/healthcare_tdm_contracts/lifecycle.py`)
- 12 new FastAPI endpoints under `/api/v1/lifecycle` (register/list/get/
  revoke dataset versions; list/get-default/upsert refresh policies;
  request/list/get/refresh/rollback environment requests;
  list-due/run-due scheduler orchestration)
- 52 new tests (21 in `services/control-plane`'s new
  `test_lifecycle_repository.py`, 14 in its new `test_lifecycle_api.py`,
  17 in `libs/contracts`'s new `test_lifecycle_contract.py`;
  `services/control-plane` is now 55 tests total, `libs/contracts` 46
  total, and `services/data-plane`'s pre-existing 378 tests continue to
  pass unmodified) -- see `problems_phase_07.md` for what's still open

## Phase 6 — what was actually delivered

- A real certification pipeline
  (`services/data-plane/src/data_plane/certification/`) that orchestrates
  every prior phase's real engine in sequence against a real Phase 1
  estate -- `data_plane.reference_data` (INGEST), `data_plane.discovery`
  (PROFILE + CLASSIFY), `data_plane.subsetting` (SUBSET),
  `data_plane.masking` (MASK), `data_plane.synthetic` (optional
  GENERATE) -- and then adds the genuinely new work: an independent
  VALIDATE gate layer, a CERTIFY stage, and an enforced PUBLISH state
  transition, run end to end against a real `tiny`-scale estate and
  demonstrated reaching `CERTIFIED`/`PUBLISHED` for a healthy run and
  `FAILED` (never publishable) for a run with a deliberately broken
  masking policy -- see `docs/tutorial/06-certification-pipeline.md`
- Eleven real, independent certification gates
  (`data_plane/certification/gates.py`): PHI/PII policy coverage,
  masking completion, referential integrity, schema validation,
  data-quality thresholds, row-count reconciliation, orphan detection,
  provenance, manifest generation, policy version recorded, masking
  version recorded -- each re-derives its answer independently rather
  than trusting an earlier phase's own report, per
  `docs/CERTIFICATION_VS_MASKING.md`
- A real, enforced six-state `CertificationStatus` lifecycle (`DRAFT` ->
  `PROCESSING` -> `CERTIFIED`/`FAILED`; `CERTIFIED` -> `PUBLISHED`/
  `REVOKED`; `PUBLISHED` -> `REVOKED`)
  (`data_plane/certification/state_machine.py`): invalid transitions
  (publishing a DRAFT/PROCESSING/FAILED/REVOKED report, skipping
  CERTIFIED entirely, revoking without a reason) are rejected by code
  and covered by adversarial tests, not merely documented as a
  convention
- A keyed-HMAC tamper-evidence mechanism for a persisted
  `certification_report.json`
  (`data_plane/certification/signing.py`) -- a hand-edited status field
  is caught by signature re-verification before any further transition
  is accepted, with its real limitation (key secrecy) documented
  honestly rather than oversold
- Extended `libs/contracts`: `CertificationStatus`,
  `CERTIFICATION_STATUS_TRANSITIONS`, `CertificationGateType`,
  `CertificationGateResult`, `CertificationReport`,
  `CertificationStatusEvent`
  (`libs/contracts/src/healthcare_tdm_contracts/certification.py`)
- Two separately tracked version identifiers on every certification
  report -- masking policy version (already existed,
  `MaskingPolicy.version`) and a new masking engine version
  (`data_plane.masking.engine.MASKING_ENGINE_VERSION`) -- per
  [ADR-0011](docs/adr/0011-masking-and-policy-versioning-for-certification.md)
- `docs/CERTIFICATION_VS_MASKING.md`: an honest account of why "masking
  ran" does not mean "certified," the new policy decisions the
  certification gates had to make (e.g. whether
  `passed_with_known_orphans` is acceptable for certification), and the
  tamper-evidence mechanism's real limits -- consistent with the honest
  tone `DATA_GOVERNANCE.md`/`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`
  already set
- 91 new tests (80 in `services/data-plane`'s new `tests/certification/`
  suite, 11 new in `libs/contracts`) -- see `problems_phase_06.md` for
  what's still open

## Phase 5 — what was actually delivered

- A real synthetic *scenario* generator
  (`services/data-plane/src/data_plane/synthetic/`) that supplements an
  already-subsetted-and-masked estate (or produces a standalone dataset)
  with deliberately constructed test scenarios, reusing Phase 4's
  `estate_io.py` read path and `writer.py` write path rather than
  reinventing them — distinct from Phase 1's `reference_data` package,
  which builds an entire estate from nothing and injects its own edge
  cases as part of that build (Phase 5 only ever augments/supplements,
  one pipeline stage later per `ARCHITECTURE.md`)
- All eleven required scenarios, implemented as real, distinct generator
  functions (`data_plane/synthetic/scenarios.py`) producing either
  schema-valid records (`normal_claims`, `high_cost_claims`,
  `unusual_prescription_combinations`, `missing_laboratory_values`,
  `boundary_dates`, `null_heavy_records`, `very_large_claim_histories`)
  or deliberately, specifically broken ones
  (`duplicate_claims`, `invalid_claim_references`, `expired_coverage`,
  `missing_provider`), each demonstrated against a real generated
  estate — see `docs/tutorial/05-synthetic-scenario-generation.md`
- `healthcare_tdm_contracts.DataProvenance` (`masked_production_like` /
  `synthetic` / `negative_test`): the vocabulary that makes "never allow
  synthetic records to be mistaken for real records" concrete, tagged
  **both** per-row (`data_provenance` column, added to every row across
  all five on-disk formats, including retagging every pre-existing base
  row `masked_production_like` when augmenting) and per-manifest
  (`SyntheticGenerationManifest.provenance_row_counts`) — see
  `data_plane/synthetic/provenance.py` for why neither alone is
  sufficient
- A scenario-sub-range ID convention
  (`data_plane/synthetic/ids.ScenarioIdAllocator`): scenario-generated
  entities use `SYN-<ENTITY>-SCEN-<seq>`, which cannot collide with
  Phase 1 estate-native `SYN-<ENTITY>-<seq>` IDs by construction;
  negative-test dangling references use the further-distinguished
  `SYN-<ENTITY>-SCEN-NX-<tag>-<seq>` shape
- Extended `libs/contracts`: `DataProvenance`, `ScenarioType` (the eleven
  scenarios), `ScenarioGenerationRecord`, `SyntheticGenerationManifest` —
  the durable, typed record of a generation run's mode (augment/
  standalone), lineage back to a Phase 4 `SubsetManifest` when one
  exists, per-scenario counts, and the full provenance rollup
  (`libs/contracts/src/healthcare_tdm_contracts/synthetic.py`)
- Both augment mode (reads an existing masked/subsetted estate, tags its
  rows, merges scenarios on top) and standalone mode (generates a small
  self-contained reference-table fixture set first, zero
  `masked_production_like` rows in the output by construction) run end
  to end against a real generated `tiny`-scale estate and a real Phase 4
  subset of it
- 85 new tests (62 in `services/data-plane`, 5 new in `libs/contracts`
  on top of the 18 already there) — see `problems_phase_05.md` for what's
  still open

## Phase 4 — what was actually delivered

- A real subsetting engine
  (`services/data-plane/src/data_plane/subsetting/`) that selects a
  referentially closed population from the real Phase 1 estate, anchored
  at `Member`, and pulls every related row across all five simulated
  source systems (`estate_io.py` reads, `closure.py` graph-walks,
  `writer.py` writes back in the same multi-format shape) — the same
  "read the real multi-format estate, do something per-row, write a new
  estate" pattern Phase 3's `dataset_masker.py` established
- All six required sizing strategies
  (`healthcare_tdm_contracts.SubsettingStrategy`), implemented as real,
  working code and each demonstrated against the real generated estate:
  `percentage`, `fixed_population`, `stratified`, `date_window`,
  `business_rule`, `risk_edge_case` (`data_plane/subsetting/selection.py`)
- Extended `libs/contracts`:
  `SubsettingStrategy`, `IntegrityStatus`, `SubsetSelectionCriteria`,
  `RelationshipEdge`, `SubsetManifest` — the durable, typed record of a
  subsetting run's source counts, selected counts, relationship edge
  counts, filter criteria, timestamp, version, estimated storage, and
  integrity status
- A three-way orphan classification
  (`data_plane/subsetting/closure.py`'s `DanglingReference.category`)
  that distinguishes a pre-existing Phase 1 source orphan (reachable from
  a real selected member, carried through and reported) from a genuine
  engine bug (an id that existed in the source but was dropped by the
  subsetting logic itself — verified never to happen against the real
  estate) from an intentional negative-test injection
  (`data_plane/subsetting/negative_testing.py`, opt-in only) — see
  `docs/tutorial/04-subsetting-and-referential-closure.md` for the full
  "reachable vs. unreachable orphans" explanation
- Population size/percentage is fully runtime-configurable (never
  hardcoded); the same code path demonstrated at `tiny` scale is what
  would run unmodified against a real `performance`-scale estate for a
  real 10,000-member subset (not yet benchmarked at that scale — see
  `problems_phase_04.md` P4-3)
- 61 new tests (57 in `services/data-plane`, 4 in `libs/contracts`) — see
  `problems_phase_04.md` for what's still open

## Phase 3 — what was actually delivered

- A real, policy-driven masking engine
  (`services/data-plane/src/data_plane/masking/`) implementing eleven
  masking techniques: redaction, nullification, unkeyed hashing,
  HMAC-based deterministic pseudonymization, a `TokenVault` tokenization
  abstraction (with a stateless HMAC-derived default and a demonstration
  stored-random-token alternative), format-preserving synthetic
  replacement, date shifting, and named specializations for email,
  phone, address, and name fields
- Extended `libs/contracts` masking shapes: `MaskingTechnique`,
  `MaskingFieldType`, and new optional `MaskingRule` fields
  (`field_pattern`, `technique`, `field_type`, `preserve_format`,
  `preserve_null`, `preserve_linkage`), additive and backward-compatible
  with the Phase 0 `MaskingStrategy`/`MaskingRule` shapes Phase 2's
  catalog already depends on — see
  [ADR-0010](docs/adr/0010-masking-technique-vocabulary.md)
- A cross-system linkage-scope table
  (`data_plane/masking/policy.LINKAGE_SCOPES`) that is the actual
  mechanism behind this phase's core requirement: a member identifier
  masks to the identical token everywhere it appears, including under
  the partner feed's legacy `pat_id` alias for the same field
- An HMAC secret key management story with no hardcoded/committed key
  anywhere: `TDM_MASKING_HMAC_KEY` env var, a gitignored `.env` fallback,
  and a `--generate-dev-key` CLI helper that never writes a key to disk
  — enforced by an automated test that scans the git-tracked (and
  about-to-be-tracked) source tree for leaked secrets
- Run end to end against the real Phase 1 synthetic estate using the
  real Phase 2 catalog to decide which technique masks which column
  (`python -m data_plane.masking.cli`), producing a masked copy of the
  `tiny` scale profile with a real member ID verified to map to the same
  masked token across Postgres, Parquet, the S3-style NDJSON clinical
  lake, and the ADLS-style CSV PBM extract (and the partner feed, under
  its `pat_id` alias)
- Masking validation (`data_plane/masking/validation.py`): referential
  integrity, no-raw-value-leakage, and token-collision checks — a
  lighter-weight precursor to the full certification pipeline
  (`ROADMAP.md` Phase 6), not a replacement for it (see
  `problems_phase_03.md` P3-1)
- 101 new tests in `services/data-plane` (210 total across the four
  Python workspace packages) covering determinism, collision handling,
  referential integrity, null handling, malformed values, idempotency,
  and secret absence — see `problems_phase_03.md` for what's still open

## Phase 2 — what was actually delivered

- A configurable, three-layer PHI/PII classification engine
  (`services/data-plane/src/data_plane/discovery/`): schema-based
  (every field of all 14 Phase 1 entities, explicitly), rule-based
  (column-name/value pattern detectors), and manual override (steward
  corrections, signed with a `confirmed_by` identity), combined with a
  documented precedence order and DATA_GOVERNANCE.md B.1's
  conservative-default rule for unrecognized columns
- Extended `libs/contracts` classification/catalog shapes:
  `SensitivityCategory` (6 labels), `ClassificationMethod`, `CatalogEntry`,
  `RetentionClassification`, built on top of (not duplicating) the
  existing Phase 0 `ClassificationTier`/`ColumnClassification`
- Run against the real, generated Phase 1 estate (not just the schema):
  a scanner (`discovery/scanner.py`) reads the actual SQLite/Parquet/
  NDJSON/CSV/partner files and catches real schema-drift columns
  (`amount_paid`, `adjustment_reason_code`, `pat_id`, `test_cd`, ...) a
  schema-only classifier would miss
- A data catalog (classification + masking requirement + source + owner +
  retention classification per column), produced as a JSON artifact and
  served read-only by the control plane
  (`GET /api/v1/catalog`, `/catalog/summary`, `/catalog/datasets`,
  `/catalog/{source_system}/{dataset}/{column}`) — see
  [ADR-0009](docs/adr/0009-catalog-artifact-handoff.md) for the
  plane-separation-respecting handoff design
- `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`: an honest account of what
  pattern/schema-based classification can and cannot prove (no free-text/
  NLP coverage, no semantic understanding, no combination/re-identification
  risk scoring) — this is explicitly not presented as a HIPAA compliance
  guarantee
- Tests across both affected packages (`libs/contracts`,
  `services/data-plane`, `services/control-plane`) — see
  `problems_phase_02.md` for what's still open

## Phase 1 — what was actually delivered

- A completely synthetic, multi-system healthcare data estate: Member,
  MemberDemographics, Address, Coverage, Plan, Provider, Claim, ClaimLine,
  Diagnosis, Procedure, Prescription, Pharmacy, Encounter, LabResult
- Distributed across 5 simulated heterogeneous sources: PostgreSQL-shaped
  (SQLAlchemy models), Parquet object storage, S3-compatible NDJSON,
  Azure/ADLS-compatible CSV, and an external partner file/API feed
- 4 configurable scale profiles (tiny/developer/qa/performance) and required
  edge cases (nulls, duplicates, orphans, malformed values, late-arriving
  data, schema drift), each guaranteed present and covered by tests
- See `services/data-plane/src/data_plane/reference_data/README.md` and
  `docs/tutorial/02-synthetic-data-estate.md` for details

## Phase 0 — what was actually delivered

- Repository structure across six architectural planes
- `ARCHITECTURE.md` describing the system, its planes, and their interfaces
- ADRs recording the foundational technical decisions (`docs/adr/`)
- `SECURITY.md`, `THREAT_MODEL.md`, `DATA_GOVERNANCE.md`, `CONTRIBUTING.md`
- `docs/tutorial/`, `docs/runbooks/`, `docs/diagrams/` seeded with real content
- `problems_master.md` established as the live problem-tracking process
- Empty/scaffold Python packages for `control-plane`, `data-plane`,
  `governance-service`, and the shared `contracts` library, each with a
  `pyproject.toml` and a documented purpose but no business logic
- Empty/scaffold React + TypeScript + Vite frontend
- Docker Compose, Terraform, and Helm scaffolding (structure only, not wired
  to real infrastructure yet)
- GitHub Actions CI workflow skeleton

## Non-goals for Phase 0

- No working application. Nothing here should be expected to run end to end.
- No real database migrations, no real masking logic, no real UI screens.
- No dependency installation was run (`pip install` / `npm install`) — config
  files are in place so a later phase can do this deliberately, once there is
  something worth installing dependencies for.
