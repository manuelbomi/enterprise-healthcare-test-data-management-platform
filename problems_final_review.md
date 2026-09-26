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

## Severity summary

| Severity | Count |
|---|---|
| P0 | 1 |
| P1 | 9 |
| P2 | 13 |
| P3 | 10 |
| **Total** | **33** |

Of these, **12 are genuinely new** (not named in any `problems_phase_NN.md`
or `problems_master.md` entry before this review): P0-1 (as a synthesized,
elevated top-level claim — see its own note on why it's listed as new despite
citing prior entries), P1-2's `/scheduler/run-due` sub-finding, P1-3, P1-4,
P1-5, P2-1, P2-9, P2-10, P2-11, P2-12, P3-8, P3-9. The remaining 21 are this
review's own independent re-inspection and severity classification of gaps
prior phases already, honestly, documented.

---

## Test suite: real results (run today, not assumed)

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

## P0 findings

### P0-1 — RBAC provides no real security boundary: there is no identity verification anywhere in the platform

- **Problem:** `control_plane.platform.rbac.authorize()` is real, enforced
  code (not a no-op) on exactly four endpoints (dataset-version revoke,
  environment rollback, policy-version approve/reject). But every one of
  those checks operates on an `actor_role` field the *caller supplies in the
  request body*, with zero verification that the caller is actually entitled
  to claim that role. There is no authentication mechanism anywhere in this
  repository — no JWT, no OAuth, no session token, no API key, nothing
  (confirmed by a repo-wide grep for `JWT|OAuth|HTTPBearer|OAuth2PasswordBearer|session_token`
  across `services/control-plane/src`: zero matches). A caller who wants to
  revoke any dataset version needs to send `{"actor_role": "PLATFORM_ADMIN", ...}`
  in the JSON body — nothing checks that the caller is who they claim, or
  that they are authorized to claim `PLATFORM_ADMIN` in the first place.
- **Risk:** For this repository's actual, stated purpose (a portfolio/
  teaching reference implementation using only synthetic data, never
  deployed), the real-world risk today is **zero** — there is no real PHI/PII
  and no real deployment for anyone to attack. But this is exactly the class
  of gap the Phase 17 prompt asks to be evaluated as if this were a
  production-readiness exercise: if this codebase were pointed at a real
  source system tomorrow, the entire RBAC layer — the only access-control
  mechanism this platform has — would provide **no actual protection**
  against an adversarial or merely careless caller. `THREAT_MODEL.md`'s own
  "Elevation of privilege" mitigation ("authorization decisions are made
  server-side by the security/governance plane, never inferred from
  client-supplied fields") is the literal opposite of what the real code
  does: the role IS a client-supplied field, and no plane verifies it.
- **Reproduction/evidence:** `services/control-plane/src/control_plane/platform/rbac.py`'s
  own module docstring states this limitation explicitly (confirmed by the
  RBAC audit performed for this review). `services/control-plane/src/control_plane/api/v1/lifecycle.py:266`
  and `:490`, `services/control-plane/src/control_plane/api/v1/governance.py:228,266`
  are the only four `authorize(...)` call sites in the entire codebase, and
  each reads `body.actor_role` (a plain Pydantic string field on the request
  body) as its input — not a decoded token, not a session lookup. A live
  demonstration: `POST /api/v1/lifecycle/dataset-versions/{id}/revoke` with
  body `{"actor_role": "PLATFORM_ADMIN", "revoked_by": "anyone", "reason": "x"}`
  succeeds regardless of who sends it.
- **Recommended fix:** This is exactly the seam `services/governance-service`
  was always intended to fill (`ARCHITECTURE.md` section 2.4: "RBAC:
  role-based authorization decisions"), and every phase since Phase 10 has
  correctly deferred it there rather than faking it. The fix is not a
  patch to `rbac.py` — it is standing up a real identity provider (even a
  minimal one: signed JWTs issued by a real login flow, verified via
  middleware before any router body is trusted) so `actor_role` is *derived*
  from a verified identity, not accepted as a bare claim. Until that exists,
  every actor-attribution field in this codebase (`revoked_by`, `performed_by`,
  `requested_by`, `generated_by`, `accessed_by`, and `actor_role` itself)
  should be documented — as it already honestly is in scattered form across
  `problems_phase_07.md` P7-6, `problems_phase_10.md` P10-2,
  `problems_phase_11.md` P11-4, `problems_phase_13.md` P13-3 — as **advisory
  metadata, not a security control**, and this review recommends stating
  that once, prominently, in `THREAT_MODEL.md` and `SECURITY.md` rather than
  leaving a reader to piece it together from four different phase files (see
  P1-1 below).
- **Why this is listed as a top-level P0 despite citing existing entries:**
  P7-6/P10-2/P11-4/P13-3 each honestly document *their own endpoint's* lack of
  RBAC. None of them, nor `ARCHITECTURE.md`, nor `THREAT_MODEL.md`, states
  the single integrated fact that matters most for a production-readiness
  verdict: the RBAC mechanism that *does* exist provides no defense at all
  against a non-cooperating caller, on any of the four endpoints it claims to
  gate, because the role itself is unauthenticated. That synthesis is this
  review's own contribution.
- **Affected files:** `services/control-plane/src/control_plane/platform/rbac.py`,
  `services/control-plane/src/control_plane/api/v1/lifecycle.py`,
  `services/control-plane/src/control_plane/api/v1/governance.py`,
  `THREAT_MODEL.md`, `SECURITY.md`.

---

## P1 findings

### P1-1 — `THREAT_MODEL.md` has never been revisited since Phase 0 and now materially misrepresents the platform's real security posture

- **Problem:** `THREAT_MODEL.md` states its own policy: *"This document is
  revisited at the end of every phase that changes a trust boundary."*
  `git log --oneline -- THREAT_MODEL.md` shows exactly one commit —
  `b8901a8`, "Phase 0: repository scaffolding" — ever. Phases 7 (metadata
  plane), 10 (governance), 11 (RBAC/audit), and 13 (evidence) all
  demonstrably changed trust boundaries and none updated this file. As a
  result it currently makes at least three claims that are now false or
  broken against the real, current codebase:
  1. Control-plane STRIDE section: *"Spoofing... Mitigation: token-based
     auth validated against the security/governance plane on every
     request; no plane trusts a caller's claim about identity without
     verifying it through the security/governance plane."* This is the
     exact opposite of the real code — see P0-1. No token-based auth exists
     anywhere, and every plane trusts a bare client-supplied field.
  2. Control-plane STRIDE section: *"Denial of service: a flood of job
     requests exhausts data-plane compute. Mitigation: control plane
     enforces quota/footprint checks before submitting jobs (see ADR on
     capacity planning, added in a later phase)."* Verified by grep: no file
     under `services/control-plane/src/control_plane/domain/lifecycle/`
     references `CapacityPlanner`/`capacity_plan`/`footprint` at all. Phase
     8's capacity planner is a separate, read-only reporting/estimation API
     (`/api/v1/capacity/*`) never wired as a gate on `POST
     /api/v1/lifecycle/environment-requests` or any other request-submission
     endpoint. No rate limiting exists anywhere either (repo-wide grep for
     `RateLimit|rate_limit|slowapi|Throttl`: zero hits).
  3. Infrastructure STRIDE section cites *"footprint management (Phase 15)"*
     for quota/expiry enforcement on snapshots — the wrong phase number.
     Footprint/capacity management is Phase 8; Phase 15 is the
     junior-engineer tutorial. Even the citation is broken, which is itself
     evidence nobody has read this section closely since it was written.
- **Risk:** Zero risk to any real data today (no real PHI/PII exists in this
  repository, matching this whole review's framing). The real risk is
  reputational/credibility for the review process itself: this repository's
  entire honesty discipline (`docs/CERTIFICATION_VS_MASKING.md`,
  `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md`, `docs/COMPLIANCE_EVIDENCE.md`
  all state, in nearly identical language, "overclaiming safety is worse
  than not claiming it") is violated by its own foundational security
  document, in the one file most likely to be read first by a security
  reviewer or an interviewer probing this repository's rigor.
- **Reproduction/evidence:** `git log --oneline -- THREAT_MODEL.md` → one
  commit. `THREAT_MODEL.md` lines 59-61 (spoofing mitigation), line 74-75
  (DoS mitigation), line 143 ("Phase 15" citation).
  `grep -rn "CapacityPlanner\|capacity_plan\|footprint" services/control-plane/src/control_plane/domain/lifecycle/`
  → no matches.
- **Recommended fix:** Rewrite `THREAT_MODEL.md`'s per-plane STRIDE
  mitigations to state what is actually built today (citing the real
  mechanisms: `control_plane.platform.rbac`, the honest "advisory metadata"
  framing from P0-1, the actual absence of quota enforcement/rate limiting),
  the same way every `docs/*.md` file written after Phase 6 already does.
  Fix the Phase 15 → Phase 8 citation. Add the revisit this document has
  been promising since Phase 0.
- **Affected files:** `THREAT_MODEL.md`.

### P1-2 — RBAC covers 4 of the ~20 real mutation endpoints, and the widest-blast-radius one is entirely unauthenticated

- **Problem:** Already tracked at the individual-endpoint level in
  `problems_phase_07.md` P7-6, `problems_phase_10.md` P10-2, and
  `problems_phase_11.md` P11-4 ("RBAC is enforced only on the four
  highest-sensitivity mutations"). This review's own re-inspection of every
  router in `services/control-plane/src/control_plane/api/v1/` found one
  concrete instance not named in any of those three entries:
  `POST /api/v1/lifecycle/scheduler/run-due` (`lifecycle.py:577-597`)
  executes a scheduled refresh for **every** currently-due environment
  request in a single call. It has no RBAC check at all (not even the "at
  least accepts an unauthenticated role claim" pattern the four gated
  endpoints have), and `triggered_by` defaults to the literal string
  `"scheduler"` with no verification the caller is an actual scheduler
  rather than an arbitrary API client. Its blast radius (every due request,
  in one call) is strictly larger than the single-request
  `POST /environment-requests/{id}/refresh` endpoint, yet it has strictly
  less protection.
- **Risk:** For this portfolio system: none (synthetic data, no real
  deployment, and a refresh only re-runs the certification pipeline against
  already-approved policies — it cannot exfiltrate or corrupt anything a
  normal refresh couldn't). For a production-readiness evaluation: this is
  a real gap — an unauthenticated endpoint that can trigger unbounded
  compute work across every environment in the system on demand is exactly
  the kind of DoS/abuse surface `THREAT_MODEL.md` claims (falsely, per P1-1)
  is mitigated.
- **Reproduction/evidence:** `services/control-plane/src/control_plane/api/v1/lifecycle.py:577-597`
  — no `authorize(...)` call in the handler body, unlike the four gated
  endpoints; `triggered_by: str = "scheduler"` default with no auth
  dependency. Confirmed via full read of all 11 router files in
  `services/control-plane/src/control_plane/api/v1/`; every other
  known-ungated mutation (dataset-version registration, environment
  request/refresh, policy draft/submit, business-consumer registration,
  consumer-request submit/fulfill, the Phase 13 access/evidence endpoints)
  was already named in P7-6/P10-2/P11-4/P13-3 — this is the one genuinely
  new gap this pass found.
- **Recommended fix:** Gate `/scheduler/run-due` behind the same RBAC
  mechanism as the other four sensitive endpoints at minimum (e.g. restrict
  to `PLATFORM_ADMIN`), and treat it as the highest-priority addition if/when
  RBAC scope is widened, given its blast radius. Longer-term, this endpoint
  should only ever be called by a trusted internal scheduler (Airflow, a
  Kubernetes CronJob), never exposed to arbitrary API callers at all — a
  network-level restriction, not just an application-level one.
- **Affected files:** `services/control-plane/src/control_plane/api/v1/lifecycle.py`.

### P1-3 — No schema-migration framework exists for the control-plane's real, evolving database

- **Problem (genuinely new finding):** `services/control-plane/src/control_plane/db/models.py`
  has grown a real, substantive SQLAlchemy schema across four separate
  phases (Phase 7: dataset lifecycle tables; Phase 10: governance tables;
  Phase 11: audit/dead-letter tables; Phase 13: no new tables, but new
  columns/queries against existing ones) — this is not a toy schema, it is
  the platform's actual system of record. Yet the *only* schema-management
  mechanism anywhere in the repository is
  `Base.metadata.create_all(engine)` (`models.py:336-340`, `init_schema`).
  There is no Alembic (or any other migration tool) anywhere in the
  repository — confirmed by `grep -rn "alembic" services/control-plane` and
  a filesystem search for `*alembic*`/`*migrat*` under
  `services/control-plane`: zero hits in either case, and the two hits for
  the word "migration" elsewhere in the repo (`problems_phase_05.md`,
  `problems_phase_13.md`) are about unrelated schema-migration *concepts*
  discussed in prose, not this actual capability gap.
  `create_all` only creates tables that do not yet exist — it has no ability
  to alter an existing table (add/rename/drop a column, change a type,
  add an index) once a database already has rows in it.
- **Risk:** Zero today — every test and demo in this repository runs
  against a fresh SQLite file created from scratch each time, so `create_all`
  has never needed to alter anything. But this is a real, structural gap for
  the platform's own stated production-readiness bar: any real deployment
  that actually persisted data across a code upgrade (the entire point of
  choosing PostgreSQL as "the system of record," `ADR-0004`) would have no
  supported way to apply the next phase's schema change without either
  manual, undocumented DDL or a destructive drop-and-recreate. Given this
  schema has already changed in 4 of the last 10 phases, the next real
  schema change is a near-certainty, not a hypothetical.
- **Reproduction/evidence:** `grep -rn "alembic\|create_all\|migration" services/control-plane/src`
  → only hit is `models.py:340: Base.metadata.create_all(engine)`.
  No `alembic.ini`, no `migrations/` or `versions/` directory anywhere in
  the repository.
- **Recommended fix:** Add Alembic (the SQLAlchemy-ecosystem standard),
  generate an initial baseline migration matching the current
  `Base.metadata`, and require every future phase that changes
  `control_plane/db/models.py` to also add a migration — the same
  discipline `CONTRIBUTING.md` already enforces for tests ("every new
  behavior needs a test"). This is squarely a "database" review-category
  finding and a natural, well-scoped Phase 18A/B item.
- **Affected files:** `services/control-plane/src/control_plane/db/models.py`,
  `services/control-plane/src/control_plane/db/session.py`.

### P1-4 — The frontend's "Audit Trail" page makes a factually false claim, and no frontend code anywhere calls the Phase 11/13 backends it was waiting for

- **Problem (genuinely new finding):** Phase 9's `AuditTrailPage.tsx`
  correctly showed an honest `NotYetAvailable` placeholder because, at the
  time, no audit log existed. Its copy reads (verbatim,
  `frontend/src/pages/AuditTrailPage.tsx`): *"The security/governance
  plane's immutable audit event log (ARCHITECTURE.md section 2.4) does not
  exist yet -- there is no backing API for this page to call..."* Phase 11
  built a real, real, DB-backed audit log (`GET /api/v1/audit/events`) and
  Phase 13 built a real evidence-package endpoint
  (`POST /api/v1/evidence/dataset-versions/{id}/package`). Neither
  `problems_phase_11.md` nor `problems_phase_13.md` records going back to
  update this page — and an exhaustive grep of `frontend/src` for
  `audit|evidence|governance` (case-insensitive) confirms **zero** code
  anywhere in the frontend calls any of these three backends: there is no
  `frontend/src/api/audit.ts`, no `evidence.ts`, no `governance.ts` — only
  `capacity.ts, catalog.ts, certification.ts, client.ts, health.ts, index.ts,
  lifecycle.ts, masking.ts, subsetting.ts, synthetic.ts, types.ts` exist.
  The false claim is locked in place by the page's own test
  (`AuditTrailPage.test.tsx`), which asserts the placeholder text renders.
  Separately, `frontend/src/api/types.ts` has no TypeScript type at all
  (not merely out of sync, per the already-tracked `problems_phase_09.md`
  P9-5) for `MaskingPolicyVersion`, `PolicyApproval`, `BusinessConsumer`,
  `ConsumerDatasetRequest` (Phase 10), `AuditEvidencePackage` (Phase 13), or
  `AuditEvent`/`AuditEventType` (Phase 11) — six real, shipped
  `libs/contracts` models the frontend has never been extended to know
  about at all.
- **Risk:** For this portfolio system: no data-safety risk (this is a
  read-only console gap, not a masking/certification defect). But it is a
  direct instance of exactly the kind of cross-phase seam the Phase 17
  prompt asked this review to hunt for ("does the frontend actually call the
  Phase 13 evidence endpoint anywhere?" — no), and the false "no backing API
  exists" claim is a genuine regression in the honesty this project holds
  itself to everywhere else — a reviewer clicking through the live console
  would be told something that has been false since Phase 11.
- **Reproduction/evidence:** `frontend/src/pages/AuditTrailPage.tsx` (copy
  quoted above); `frontend/src/api/` directory listing (11 files, none named
  audit/evidence/governance); grep of `frontend/src` for
  `audit|evidence|governance` returning only the placeholder copy, a nav
  label, and unrelated English-word matches (e.g. "tamper-evidence
  signature" in `CertificationPage.tsx`).
- **Recommended fix:** Either build the (small, read-only, following the
  exact `ADR-0009`/Phase-9 JSON-artifact-repository pattern already used for
  masking/subsetting/synthetic/certification) `frontend/src/api/audit.ts` +
  an `AuditTrailPage` that actually renders `GET /api/v1/audit/events`, or,
  at minimum, correct the placeholder copy to stop claiming no backend
  exists and instead say "not yet wired into this console" — the latter is a
  ~10-minute fix that immediately restores honesty even before the former is
  scheduled. Add the six missing TypeScript types to `types.ts` regardless
  of whether a page consumes them yet, so `problems_phase_09.md` P9-5's
  "drift" framing at least starts from complete coverage.
- **Affected files:** `frontend/src/pages/AuditTrailPage.tsx`,
  `frontend/src/pages/AuditTrailPage.test.tsx`, `frontend/src/api/types.ts`,
  `frontend/src/api/` (missing `audit.ts`/`evidence.ts`/`governance.ts`).

### P1-5 — `ARCHITECTURE.md`'s observability claim is 100% unimplemented, and nothing has ever flagged it

- **Problem (genuinely new finding):** `ARCHITECTURE.md` section 3.3 states:
  *"Every plane emits structured logs (JSON, correlation-ID tagged), metrics
  (job duration, rows processed, storage footprint, masking coverage), and
  traces (a request through control plane -> data plane -> metadata plane is
  one trace). Audit events... are a distinct stream from operational
  logs."* A repo-wide grep across all of `services/` for
  `logging|structlog|getLogger|correlation|trace_id|opentelemetry|prometheus|statsd|metrics\.`
  found: zero real logging setup, zero structured/JSON logging, zero
  correlation-ID mechanism, zero metrics emission (Prometheus/StatsD/any),
  zero distributed tracing. The only near-hit is a dead configuration field:
  `control_plane.config.Settings.log_level` is validated at startup
  (`config.py:51,115-124`, and tested by `test_config_validation.py`) but is
  **never read by anything** — it is not passed to `logging.basicConfig` or
  any handler anywhere in the codebase. The claim "audit events are a
  distinct stream from operational logs" is also literally false: there is
  no operational log stream at all for the audit table to be "distinct
  from" — `AuditLogRepository` (Phase 11) is the *only* logging-like
  mechanism that exists anywhere, and it uses plain `session.add()`, not any
  Python `logging` call.
- **Risk:** For this portfolio system: none directly (every test/demo
  captures its own evidence via JSON artifacts and DB rows, which is a
  legitimate substitute at this scale). For production readiness
  specifically: this is a real, unmitigated operational blind spot — no way
  to correlate a request across the control plane and a data-plane job run,
  no way to alert on job duration/throughput regressions outside of manually
  re-running `data_plane.benchmarks`, no centralized log aggregation story at
  all.
- **Reproduction/evidence:** grep results above (zero hits for every real
  observability library/pattern across all four Python packages); a
  repo-wide search of every `problems_phase_NN.md`/`problems_master.md` for
  "observability", "structured log", "trace"/"correlation", "metrics"
  (case-insensitive) returns only false positives (a PySpark stack-trace
  mention in `problems_phase_14.md`, and "audit logging" meaning the DB
  table in `problems_phase_11.md`) — this specific gap has never been
  recorded anywhere before this review.
- **Recommended fix:** Either scope this claim down honestly in
  `ARCHITECTURE.md` (the same way every other aspirational Phase-0 claim in
  that document has been progressively corrected phase-by-phase in its own
  "Phase N note" sections) to say what actually exists — JSON artifacts and
  DB rows, no logging/metrics/tracing infrastructure — or treat "basic
  structured logging with a correlation ID, wired to the existing
  `log_level` config field" as a well-scoped, high-value Phase 18 item; it
  is one of the cheapest real gaps in this review to close.
- **Affected files:** `ARCHITECTURE.md` (section 3.3),
  `services/control-plane/src/control_plane/config.py`.

### P1-6 — Masking's per-source-system writers are not atomic; a mid-run crash can leave one truncated, plausible-looking file

- **Problem:** Already tracked precisely as `problems_phase_11.md` P11-1.
  Re-verified directly against the current code: `mask_estate`
  (`services/data-plane/src/data_plane/masking/dataset_masker.py:415-442`)
  writes a whole-run `_MASKING_RUN_INCOMPLETE.marker` at the start and
  removes it only on full completion — this is real and correctly tested.
  But its own docstring (lines 429-441) states explicitly that this does
  **not** make each individual per-source-system masker's writes atomic;
  `mask_clinical_data_lake` writes NDJSON rows into an already-open file
  handle one at a time, so a crash mid-write leaves one truncated file for
  whichever source system was in progress, indistinguishable from a valid
  file except via the run-level marker.
- **Risk:** For this portfolio system: low — the runbook
  (`docs/runbooks/masking-job-failure-recovery.md`) correctly instructs
  "delete the whole output directory, never resume," which fully mitigates
  the gap operationally. For production readiness: a masking pipeline where
  an individual output file's own byte-level completeness cannot be trusted
  independent of a separate marker file is a real robustness gap that would
  need closing before this engine ran unattended, at scale, without a human
  checking the marker every time.
- **Reproduction/evidence:** `services/data-plane/src/data_plane/masking/dataset_masker.py:404-409`
  (docstring: "does **not** guarantee every individual file... is itself
  complete"); `test_masking_job_crash_leaves_an_incomplete_marker_not_silent_partial_output`
  proves the run-level marker but "does not assert anything about the
  byte-level completeness of the one partially-written NDJSON file itself"
  per the test's own documented scope.
- **Recommended fix:** As `problems_phase_11.md` P11-1 itself recommends:
  change each per-source-system masker to write to a temporary path and
  rename atomically on completion. Scoped as a deliberately deferred,
  higher-risk refactor of code covered by ~80 existing tests — a reasonable,
  well-bounded Phase 18 candidate.
- **Affected files:** `services/data-plane/src/data_plane/masking/dataset_masker.py`.

### P1-7 — Both tamper-evidence mechanisms (certification HMAC, evidence-package checksum) are defeatable by anyone with database/filesystem write access plus the key

- **Problem:** Already tracked as `problems_phase_03.md` P3-2,
  `problems_phase_06.md` P6-2, `problems_phase_13.md` P13-2, and explained at
  length in `docs/CERTIFICATION_VS_MASKING.md` and
  `docs/COMPLIANCE_EVIDENCE.md`. Re-confirmed directly: the certification
  report's keyed HMAC-SHA256 (`data_plane/certification/signing.py`) requires
  both file access and the signing key to forge — a real detection, not
  prevention, mechanism, and the key itself has no secrets-provider-backed
  storage (env var / `.env` only, same as the masking key). The evidence
  package's `bundle_checksum` (Phase 13) is a **plain, unkeyed** SHA-256 —
  anyone with database write access alone (no key needed at all) can edit
  the underlying rows and regenerate a self-consistent checksum.
- **Risk:** For this portfolio system: none (no adversary with database
  write access exists; this is documented, deliberate, and honestly scoped
  as "corruption detection," never "non-repudiation," in
  `docs/COMPLIANCE_EVIDENCE.md`). For production readiness: an auditor
  relying on either mechanism as evidence a dataset/record wasn't tampered
  with needs to understand this limit precisely — the evidence package in
  particular provides *weaker* protection than the certification report it
  may embed, which is a subtlety easy to miss if a reader only skims one of
  the two documents.
- **Reproduction/evidence:** `data_plane/certification/signing.py`'s module
  docstring; `control_plane.domain.evidence.compute_bundle_checksum`'s use
  of unkeyed `hashlib.sha256` (per `docs/COMPLIANCE_EVIDENCE.md`'s own
  "checksum is an integrity check, not a signature" section, independently
  confirmed against ADR-0016).
- **Recommended fix:** Already correctly named in `problems_phase_13.md`
  P13-2 and `docs/interview/tradeoffs.md` item 3: a real production
  deployment wanting external, independently-verifiable non-repudiation for
  either artifact needs an asymmetric signature (public/private keypair)
  backed by a real secrets provider, not implemented anywhere in this
  repository. No change recommended for the portfolio scope; flagged here so
  a reader of this review sees both artifacts' real limits side by side.
- **Affected files:** `services/data-plane/src/data_plane/certification/signing.py`,
  `services/control-plane/src/control_plane/domain/evidence/`.

### P1-8 — No enforced link between a registered `DatasetVersion`'s claimed masking policy and Phase 10's governed, approved policy version

- **Problem:** Already tracked as `problems_phase_10.md` P10-1. Re-confirmed:
  `LifecycleRepository.register_dataset_version` never calls into
  `GovernanceRepository.get_approved_policy_version` — an operator can run
  the certification pipeline with a hand-built `MaskingPolicy` that was never
  drafted/approved through Phase 10's governance workflow at all, and Phase
  7 will register the resulting `DatasetVersion` without complaint, purely
  by convention (the demo scripts always pass the actually-approved policy
  object, but nothing enforces that discipline in code).
- **Risk:** For this portfolio system: none (both demo paths are internally
  consistent). For production readiness: this is the exact gap that would
  let an ungoverned masking policy reach a published dataset while every UI
  and API surface implies governance was followed — a real compliance-integrity
  hole for an organization actually relying on the governance layer to mean
  something.
- **Reproduction/evidence:** as documented in `problems_phase_10.md` P10-1:
  `run_certification_pipeline(..., masking_policy=some_other_policy)` with a
  never-approved policy, then `POST /api/v1/lifecycle/dataset-versions` with
  the resulting report, registers successfully.
- **Recommended fix:** As P10-1 already recommends: add a certification gate
  or a `LifecycleRepository`-side check against
  `GovernanceRepository.get_approved_policy_version` before registration
  succeeds.
- **Affected files:** `services/control-plane/src/control_plane/domain/lifecycle/repository.py`,
  `services/control-plane/src/control_plane/domain/governance/repository.py`.

### P1-9 — No verification anywhere in the pipeline that masked numeric data preserves the source's statistical distribution

- **Problem:** Already tracked as `problems_phase_03.md` P3-4 and
  `problems_phase_06.md` P6-3, and explained in
  `docs/CERTIFICATION_VS_MASKING.md`. Confirmed unchanged through Phase 16:
  `data_plane.masking.synthesizers`'s numeric replacement preserves
  per-value plausibility (same order of magnitude) only; no gate anywhere
  (`check_data_quality_thresholds` is an explicit non-degeneracy check only)
  compares masked-vs-source mean/variance/percentile shape.
- **Risk:** For this portfolio system: low (the gap is honestly documented
  everywhere it's relevant, and the platform never claims otherwise). For
  production readiness: this is a real gap in the core value proposition —
  "test data that looks and behaves like production" (`ARCHITECTURE.md`
  section 1) is only partially true for numeric fields; a load/perf/analytics
  test relying on realistic dollar-amount distributions would not get them.
- **Reproduction/evidence:** mask a `tiny`-scale estate and compare the
  distribution of masked `billed_amount` to the original — same rough order
  of magnitude only, per the already-documented repro in P3-4/P6-3.
- **Recommended fix:** As already named: a future data-quality-focused phase
  once the metadata plane holds real aggregate statistics to compare
  against, per P5-1's same owner note.
- **Affected files:** `services/data-plane/src/data_plane/masking/synthesizers.py`,
  `services/data-plane/src/data_plane/certification/gates.py`.

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
