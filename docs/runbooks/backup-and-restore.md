# Runbook: backup and restore the metadata plane database

> **Status:** REAL procedure (Phase 11) -- unlike `disaster-recovery.md`
> (still an intended procedure awaiting the Phase 21 drill),
> the commands below are exercised against the actual schema this
> repository ships: `control_plane.db.models` (Phase 7's dataset
> lifecycle tables, Phase 10's governance tables, and Phase 11's
> `audit_event`/`dead_letter_event` tables), backing
> `TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL`. Complements
> `disaster-recovery.md` (which covers *responding* to a loss) with the
> concrete, testable mechanics of *taking and restoring a backup* in
> the first place.

## Symptom / when to use this runbook

- Scheduled preventive maintenance (routine backups before a schema
  migration, before a risky bulk operation, or on a recurring cadence).
- Recovering from a bad write (a manual data-fix script that went
  wrong, a bug that corrupted rows) where `disaster-recovery.md`'s
  "restore from a backup" step needs a backup to actually exist and a
  known-good restore procedure.

## Impact

None if performed proactively (a backup is a read operation against
the live database). A *restore* is disruptive: it replaces the current
database state with the backup's state, so anything written after the
backup was taken is lost unless separately reconciled (see
`disaster-recovery.md`'s "Reconcile" step for the general pattern —
comparing the restored state against object storage's actual
snapshots).

## Diagnosis (before restoring)

1. Confirm which database backend is in use:
   `echo $TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL` (default, if unset:
   `sqlite:///data/tmp/control-plane/lifecycle.db` — see
   `control_plane/config.py`). The procedure differs for SQLite (local
   dev, this repository's default) vs. PostgreSQL (a real deployment,
   per [ADR-0004](../adr/0004-postgresql-metadata-store.md)).
2. Confirm the backup you intend to restore from is from *before* the
   issue you're recovering from — restoring a backup taken after
   corruption already occurred does not help.
3. Take a fresh backup of the *current* (possibly bad) state before
   restoring anything, in case the restore itself needs to be undone or
   the "bad" state turns out to contain data worth recovering
   selectively.

## Backup procedure

### SQLite (local dev / this repository's zero-infrastructure default)

SQLite's own `.backup` command produces a consistent snapshot even
while the database is in use (it does not require stopping the control
plane process):

```bash
# Default path, per control_plane/config.py's lifecycle_database_url:
sqlite3 data/tmp/control-plane/lifecycle.db ".backup 'data/tmp/control-plane/lifecycle.backup.$(date +%Y%m%d-%H%M%S).db'"
```

Verify the backup is a real, openable database (not a truncated/failed
copy) before trusting it:

```bash
sqlite3 data/tmp/control-plane/lifecycle.backup.<timestamp>.db "SELECT COUNT(*) FROM dataset_version;"
```

### PostgreSQL (a real deployment, per ADR-0004)

```bash
pg_dump "$TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL" \
  --format=custom \
  --file="lifecycle-backup-$(date +%Y%m%d-%H%M%S).dump"
```

`--format=custom` (not plain SQL) allows selective table restore later
if only one table needs recovering (e.g. only `audit_event` was
corrupted, not the whole schema).

## Restore procedure

### SQLite

```bash
# Stop the control-plane process first -- SQLite restore is not safe
# to do against a live writer.
cp data/tmp/control-plane/lifecycle.backup.<timestamp>.db data/tmp/control-plane/lifecycle.db
# Restart the control-plane process.
```

### PostgreSQL

```bash
# Restore into a NEW database first, never directly over the live one,
# so the restore can be verified before cutting over:
createdb tdm_metadata_restore_check
pg_restore --dbname=tdm_metadata_restore_check lifecycle-backup-<timestamp>.dump

# After verification (spot-check row counts, check the most recent
# dataset_version / audit_event rows look right), cut over:
# 1. Stop the control-plane process(es).
# 2. Rename/swap the database, or point
#    TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL at the restored one.
# 3. Restart.
```

## What a restore does and does not recover

- **Recovers**: every table's row data as of the backup's timestamp --
  dataset versions, refresh policies, environment requests,
  refresh/rollback history, governance policy versions/approvals,
  business consumers/consumer requests, and (Phase 11) the audit event
  log and dead-letter event log.
- **Does not recover**: the actual masked/subsetted data files
  themselves (`storage_uri` values point at object storage, which this
  runbook does not back up -- see `disaster-recovery.md`'s "Object
  storage loss" section for that, and `ARCHITECTURE.md` section 3.4 for
  why the metadata-plane and object-storage recovery stories are
  deliberately separate: metadata is comparatively cheap and fast to
  back up/restore; multi-terabyte object storage relies on
  reproducibility from recorded lineage instead).
- **Does not recover**: anything written to the database *after* the
  backup was taken. Reconcile against object storage's actual state
  using the same pattern `disaster-recovery.md` documents for a full
  metadata-plane loss.

## Prevention / follow-up

- No automated backup schedule exists in this repository yet (no cron
  job, no managed-database automated-backup configuration) -- this is
  a real, open gap for whichever phase stands up real infrastructure
  (`infra/docker-compose`, a real cloud Postgres instance). Track it in
  `docs/problems/problems_master.md` against that phase, not silently assume it's
  handled.
- Every write this database receives is already independently
  reconstructable in principle from upstream sources for the
  Phase 7/10 tables specifically tied to a `CertificationReport`
  (`DatasetVersionRow.certification_report_id`) -- a truly catastrophic
  loss with no backup at all is recoverable, just expensive (re-run
  every certification pipeline, re-register every version, re-approve
  every policy version), unlike the audit/dead-letter event logs
  (Phase 11's own tables), which have no upstream source to
  reconstruct from and are only as safe as this runbook's backup
  cadence.
