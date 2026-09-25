# Runbooks

Operational runbooks for running and recovering this platform. Most of
these were written in Phase 0, ahead of implementation, describing
*intended* procedures so later phases build toward a known operational
target rather than bolting on operations as an afterthought — each is
marked with its own status line noting whether it has since been
validated against real, running code. As of Phase 11, three runbooks
are REAL, tested procedures against the actual Phase 7/10/11 schema and
code (see their own status lines); the rest remain intended procedures
pending the phase that implements the relevant capability
(`snapshot-refresh-failure.md`/`disaster-recovery.md`, both still
written against not-yet-built orchestration/multi-region
infrastructure).

## Index

- [`incident-response-template.md`](incident-response-template.md) — the
  shape every incident response runbook in this repository should follow
- [`snapshot-refresh-failure.md`](snapshot-refresh-failure.md) — what to do
  when a scheduled snapshot refresh fails
- [`disaster-recovery.md`](disaster-recovery.md) — recovering the platform
  after loss of the metadata database or object storage
- [`backup-and-restore.md`](backup-and-restore.md) — **REAL (Phase 11)**:
  taking and restoring a backup of the actual metadata-plane database
  (SQLite locally, PostgreSQL for a real deployment)
- [`masking-job-failure-recovery.md`](masking-job-failure-recovery.md) —
  **REAL (Phase 11)**: diagnosing and recovering from a masking job that
  crashed mid-run or produced corrupted output, backed by real
  failure-injection tests
- [`duplicate-requests-and-revoked-datasets.md`](duplicate-requests-and-revoked-datasets.md) —
  **REAL (Phase 11)**: a duplicate refresh/registration request, and a
  business consumer requesting a dataset whose only version was
  revoked, both backed by real failure-injection tests

## Conventions

Every runbook answers, in order:

1. **Symptom** — how you notice this situation
2. **Impact** — who/what is affected and how badly
3. **Diagnosis** — how to confirm this is actually what's happening
4. **Resolution** — the steps to fix it
5. **Prevention / follow-up** — what should change so it's less likely next
   time, and where that follow-up is tracked (usually `problems_master.md`
   or a new ADR)
