# Runbook: disaster recovery — metadata plane or object storage loss

> **Status:** intended procedure, written ahead of implementation (Phase 0).
> Will be exercised as an actual drill in Phase 21. Treat this as the
> design target for that phase, not a validated procedure yet.

## Symptom

Either: (a) the PostgreSQL metadata database is unavailable or has lost
data, or (b) the object storage backend (MinIO locally / S3 / ADLS in the
cloud) is unavailable or has lost data. These are handled differently
because of the "metadata + reproducibility" pattern described in
`ARCHITECTURE.md` section 3.4.

## Impact

- **Metadata loss**: the control plane cannot resolve catalogs,
  classifications, job status, or snapshot registry entries. The data
  itself (already-published snapshots in object storage) is untouched and
  not lost, but is temporarily unreachable/unindexed through the platform.
- **Object storage loss**: published snapshots and staging data are
  unavailable or gone. Metadata *about* them may still exist (what was
  produced, by which job, with which policy) even though the data itself is
  gone.

## Diagnosis

1. Confirm which system is actually affected — check infrastructure health
   for PostgreSQL vs. the object storage backend independently; don't
   assume one implies the other, since they are deliberately independent
   systems (ADR-0003 plane separation).
2. For metadata loss: determine whether this is a full loss (restore from
   the database's own backup/replication, which is an infrastructure-layer
   concern outside this repository's scope) or a partial/corruption issue.
3. For object storage loss: determine which snapshots/objects are actually
   missing vs. merely slow/unreachable.

## Resolution

### Metadata plane loss

1. Restore PostgreSQL from its most recent backup/replica (infrastructure-
   layer procedure, provider-specific — e.g., RDS/Cloud SQL automated
   backups in a real cloud deployment).
2. Reconcile: compare the restored metadata plane's snapshot registry
   against what actually exists in object storage. Any snapshot present in
   storage but missing from the restored metadata (because it was written
   after the backup was taken) needs its metadata record rebuilt from the
   object's own manifest (each published snapshot carries enough
   self-describing metadata — policy version, job run ID, row counts — to
   reconstruct its registry entry without re-running the job).
3. Resume normal operation; verify the orchestrator picks up scheduled
   refreshes correctly against the reconciled state.

### Object storage loss

1. Identify affected snapshots via the (intact) metadata plane's lineage
   records — every snapshot's job run, source dataset, and policy version
   are known even if the output bytes are gone.
2. Re-run the producing job(s) from source, using the recorded policy
   version, to regenerate the lost snapshot(s). This is the reason lineage
   records the policy version explicitly rather than "whatever the current
   policy is" — a regenerated snapshot must be reproducible even if the
   policy has since changed.
3. Republish as a new snapshot object; update the metadata plane's storage
   location reference.
4. If the original source data has itself changed since the lost snapshot
   was first produced, the regenerated snapshot will not be byte-identical
   to the original — document this explicitly to consumers rather than
   presenting it as a silent, perfect restore.

## Prevention / follow-up

- This "metadata + reproducibility" pattern is deliberately chosen over
  replicating full multi-terabyte lower-environment datasets across
  regions (see `ARCHITECTURE.md` 3.4) — cheaper, and it is exercised for
  real, not just assumed, in the Phase 21 disaster-recovery drill.
- Any gap found during a real drill (metadata insufficient to reconstruct
  an object, a job that isn't actually reproducible from recorded inputs)
  is a Sev-level finding, tracked in `docs/problems/problems_master.md` against the
  phase that owns the affected component, not silently worked around.
