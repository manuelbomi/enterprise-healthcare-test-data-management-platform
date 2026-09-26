# Changelog

All notable changes to this repository are recorded here, phase by phase,
following the spirit of [Keep a Changelog](https://keepachangelog.com/) --
adapted for a promptbook-driven, phase-numbered build rather than a
traditional release cadence. See `ROADMAP.md` for the full "what was
actually delivered" account of every phase; this file is the versioned
summary of the same history.

## Versioning convention (adopted this phase, Phase 18B)

Every workspace package in this repository -- `libs/contracts`,
`services/control-plane`, `services/data-plane`,
`services/governance-service`, and `frontend` -- shares one version
number, bumped together, rather than being versioned independently per
package. This repository has never cut a real external release (per
`problems_final_review.md`'s original P3-8 finding, tracked since
Phase 0: all five packages sat at the placeholder `0.1.0` through
Phase 18A, unchanged since the repository's first commit), so
per-package independent versioning would track a distinction
(different packages evolving at different paces) that has not actually
happened yet -- every phase from 0 through 18A touched multiple
packages together. Going forward:

- **MAJOR** -- a breaking contract change (a `libs/contracts` shape
  changes incompatibly, e.g. a field removed or its meaning changed) or
  a breaking API/route change with no migration path.
- **MINOR** -- a phase (or fix cycle) that adds real, backward-compatible
  functionality -- new endpoints, new contract fields, new capabilities.
  This is the common case; almost every phase in this history would have
  been a MINOR bump had this convention existed from Phase 0.
  **This is 0.2.0**, covering everything Phase 18B added on top of
  0.1.0's Phase 0-18A baseline (below).
- **PATCH** -- a fix-and-delete cycle (like Phase 18A/18B) that closes
  findings without adding new user-facing capability, or a
  documentation/citation-accuracy-only change.

0.1.0 is treated as the single baseline for "everything Phase 0 through
Phase 18A built" rather than reconstructed phase-by-phase after the
fact -- see `ROADMAP.md` for that real, detailed, phase-by-phase account
(it is the authoritative history; this file summarizes it in
Keep-a-Changelog form starting from the point this convention was
adopted).

## [0.2.0] - Phase 18B - fix/delete cycle for P2/P3 findings

Resolves the P2/P3 findings from `problems_final_review.md` (Phase 17's
production-readiness review) that were genuinely fixable at proportionate
scope; the remainder are left explicitly open with updated reasoning
(the phase's own "leave unresolved problems documented" permission,
exercised deliberately for the handful of findings that name a
disproportionate, previously-deferred build -- a real storage adapter,
real NLP-based PHI detection, real Delta Lake writes, a full frontend
CRUD workflow -- rather than fabricating a toy version of any of them).
See `ROADMAP.md`'s "Phase 18B -- what was actually delivered" section for
the complete per-finding accounting.

### Added
- Postgres connection-pool resilience (`pool_pre_ping`, `pool_recycle`,
  explicit `pool_size`/`max_overflow`) on every real Postgres engine
  (control-plane and data-plane) (P2-1).
- A real, database-enforced distributed lock
  (`control_plane.platform.scheduler_lock`) serializing concurrent
  `POST /api/v1/lifecycle/scheduler/run-due` sweeps, refusing an
  overlapping sweep with HTTP 409 rather than allowing it to race (P2-2).
- `scripts/run_scheduled_maintenance.py`, a real, runnable, idempotent
  entry point for the retention sweep and vacuum-candidate identification
  -- the missing "run this periodically, by any means" caller (P2-3).
- `scripts/check_doc_code_citations.py`, a real automated cross-check
  that every module-path/route citation in `ROADMAP.md`,
  `docs/interview/*.md`, and `docs/tutorial/guide/*.md` still resolves
  against the live source tree; caught and fixed two genuinely stale
  citations in `docs/interview/scaling.md` as a direct result (P2-9).
- `REJECTED`/`CANCELLED` as real, enforced terminal states for
  `ConsumerRequestStatus`, with a full transition table
  (`CONSUMER_REQUEST_STATUS_TRANSITIONS`) and two new endpoints
  (`POST /api/v1/governance/consumer-requests/{id}/reject`,
  `.../cancel`), mirroring the exact state-machine pattern
  `data_plane.certification.state_machine`/
  `control_plane.domain.lifecycle.state_machine` already use (P3-4).
- `healthcare_tdm_contracts.MaskingRunSummary`, a shared typed contract
  for the `masking_run_summary.json` artifact, now constructed by both
  real writers (`data_plane.masking.cli`,
  `data_plane.certification.pipeline`) and imported directly by the one
  real reader (`control_plane.artifacts.masking`) instead of each
  maintaining its own copy of the same shape (P3-7).
- Root and `frontend/` `.dockerignore` files (P2-12).
- This `CHANGELOG.md`, and the shared cross-package versioning
  convention described above (P3-8).
- A loud, non-silent signal (a real `UserWarning` plus a per-run terminal
  summary line) for the three data-dependent `pytest.skip(...)` calls in
  `services/data-plane`'s test suite (P3-9).

### Fixed
- `infra/terraform/aws/main.tf`'s header comment cited a phantom
  "Phase 20"; corrected to cite the real Phase 12 decision (P2-10).
- `services/governance-service`'s `audit/__init__.py` docstring claimed
  audit logging was "Implemented in Phase 3" (never true); corrected to
  point at the real Phase 11 implementation in
  `control_plane.platform.audit` (P2-11).

### Documentation
- Updated `problems_final_review.md` entries for findings investigated
  but deliberately left open this phase (re-affirmed, not left stale),
  each with this phase's own re-verification evidence and reasoning.

## [0.1.0] - Phases 0-18A - initial build

The entire portfolio-grade Enterprise Healthcare Test Data Management
platform through Phase 18A, tracked as a single baseline version rather
than reconstructed release-by-release (this versioning convention did
not exist until Phase 18B -- see above). In brief, by theme (see
`ROADMAP.md` for the authoritative, detailed, phase-by-phase account of
every one of these):

- **Phase 0** -- repository operating rules, architecture docs, ADRs,
  five-service workspace scaffolding.
- **Phase 1** -- a synthetic healthcare data estate across 5
  heterogeneous source systems (Postgres, Parquet, CSV, NDJSON, a
  partner JSON feed), with deliberately injected referential-integrity
  edge cases.
- **Phase 2** -- PHI/PII discovery and classification engine (regex/
  schema-based) plus a data catalog.
- **Phase 3** -- the enterprise deterministic masking engine
  (HMAC-pseudonymization, tokenization, format-preserving synthetic
  replacement, generalization, redaction).
- **Phase 4** -- referentially intact, production-scale data subsetting
  (six anchor-selection strategies).
- **Phase 5** -- synthetic test-data generation for scenario/edge-case
  coverage.
- **Phase 6** -- the certified test-dataset pipeline (ingest through
  certify/publish) with eleven real certification gates.
- **Phase 7** -- dataset lifecycle and refresh management (versions,
  refresh cadence, retention, rollback).
- **Phase 8** -- storage/compute footprint measurement and capacity
  planning.
- **Phase 9** -- the React/TypeScript enterprise TDM web console
  (read-only).
- **Phase 10** -- centralized enterprise masking governance across
  named business consumers (`LEFT_ARM`/`RIGHT_ARM`).
- **Phase 11** -- platform integrity: RBAC, audit logging,
  health/readiness, dead-letter handling, retry/backoff (RBAC's role
  claim was not backed by a verified identity until Phase 18A's real
  authentication layer -- see below).
- **Phase 12** -- CI/CD (GitHub Actions), Kubernetes/Helm, and a real
  Terraform Azure example.
- **Phase 13** -- auditability and compliance evidence packages
  (tamper-evident signing).
- **Phase 14** -- scale/performance engineering: real PySpark
  masking/subsetting jobs and measured throughput benchmarks.
- **Phase 15** -- a complete 20-chapter junior-engineer tutorial.
- **Phase 16** -- interview/system-design documentation (four files).
- **Phase 17** -- the principal-engineer production readiness review
  that produced `problems_final_review.md`'s original 33 findings
  (review only -- no fixes).
- **Phase 18A** -- fixed all 10 P0/P1 findings from Phase 17, including
  the real minimal JWT identity layer for RBAC (ADR-0018) and the
  governed-vs-ungoverned dataset-version registration split (ADR-0019).

[0.2.0]: https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform
[0.1.0]: https://github.com/manuelbomi/enterprise-healthcare-test-data-management-platform
