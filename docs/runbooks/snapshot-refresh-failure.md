# Runbook: scheduled snapshot refresh failure

> **Status:** intended procedure, written ahead of implementation (Phase 0).
> Will be validated once a real job orchestrator exists (not yet
> scheduled by name as of Phase 14 — Phase 14 turned out to be
> scale/performance benchmark tooling, not job-orchestration wiring; see
> `problems_phase_14.md`). Treat the specific commands/endpoints below as
> illustrative until then.

## Symptom

A scheduled snapshot refresh (e.g., the weekly `qa-claims` refresh) did not
produce a new snapshot version by its expected time. Noticed via: the
orchestrator's job-status dashboard showing a `failed` or `stuck` job, an
alert from the observability stack on job duration/absence, or a consumer
reporting their environment's data is stale.

## Impact

- The consuming lower environment continues serving its *previous*
  snapshot version — this is a safe default (snapshots are immutable once
  published; a failed refresh cannot corrupt an already-published
  snapshot), but the data is now stale relative to the refresh cadence
  policy.
- No PHI/PII exposure risk from a refresh failure alone, since failed jobs
  are blocked from publishing by certification (see ARCHITECTURE.md
  section 2.2) before any output becomes visible to consumers. If
  diagnosis reveals a job *did* publish without passing certification,
  treat this as a security incident, not a routine refresh failure —
  escalate per `SECURITY.md`.

## Diagnosis

1. Check the job run record in the metadata plane's lineage table for the
   failed run: which stage failed (subsetting, masking, certification,
   publish)?
2. If subsetting/masking failed: check the data-plane job logs (structured,
   correlation-ID tagged — see `ARCHITECTURE.md` 3.3) for the failing
   stage's error.
3. If certification failed: this means the job *ran* but its output did not
   meet the masking policy — check the certification evidence record for
   which specific check failed (e.g., a raw identifier was detected, or
   referential integrity broke). This is a signal to investigate the
   masking policy or the source schema change that broke an assumption, not
   just to retry blindly.
4. If the job appears stuck (no terminal status): check data-plane compute
   (is the Spark cluster/session healthy?) and control-plane orchestrator
   health.

## Resolution

1. If the failure is a transient infrastructure issue (compute unavailable,
   storage timeout): retry the job through the orchestrator. Idempotency of
   job submission means a retry is safe.
2. If the failure is a certification failure: **do not** manually override
   certification to force a publish. Fix the underlying cause (policy gap,
   source schema drift) and re-run. Certification failing is the system
   working as designed, not a bug to route around.
3. If the failure is a code bug in a data-plane job: file/update the
   relevant phase's problem entry in `problems_master.md` with repro
   details, fix, add a regression test, then retry the refresh.
4. Consumers remain on the previous snapshot version throughout — no action
   needed on their end unless the staleness itself is now a problem, in
   which case communicate expected resolution time.

## Prevention / follow-up

- Track recurring refresh failures (same job, same failure class, more than
  once) as a `problems_master.md` entry against the phase that owns the
  failing component, not just as a one-off retry.
- If certification catches a real policy gap, that's a signal
  `DATA_GOVERNANCE.md`'s policy needs updating — open the update as part of
  the same fix, not as separate deferred work.
