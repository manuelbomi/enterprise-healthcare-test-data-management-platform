# Runbooks

Operational runbooks for running and recovering this platform. As of
Phase 0, no part of the platform is actually deployed anywhere, so these
runbooks describe *intended* procedures — written now, ahead of
implementation, so later phases build toward a known operational target
rather than bolting on operations as an afterthought. Each runbook will be
validated against the real system (and corrected if reality diverges) as
the phase that implements the relevant capability lands.

## Index

- [`incident-response-template.md`](incident-response-template.md) — the
  shape every incident response runbook in this repository should follow
- [`snapshot-refresh-failure.md`](snapshot-refresh-failure.md) — what to do
  when a scheduled snapshot refresh fails
- [`disaster-recovery.md`](disaster-recovery.md) — recovering the platform
  after loss of the metadata database or object storage

## Conventions

Every runbook answers, in order:

1. **Symptom** — how you notice this situation
2. **Impact** — who/what is affected and how badly
3. **Diagnosis** — how to confirm this is actually what's happening
4. **Resolution** — the steps to fix it
5. **Prevention / follow-up** — what should change so it's less likely next
   time, and where that follow-up is tracked (usually `problems_master.md`
   or a new ADR)
