# tdm-data-plane

The data plane: PySpark jobs that discover, subset, mask, and synthesize
healthcare test data. See `ARCHITECTURE.md` section 2.2 at the repository
root for full responsibilities.

Every job in this package is designed to run identically against a local
Spark session (backed by MinIO for storage) and against a real Spark
cluster / Databricks runtime (backed by S3 or ADLS) — see
`docs/adr/0005-object-storage-abstraction.md` and
`docs/adr/0007-delta-parquet-data-format.md`. Job code depends only on the
storage adapter interface in `libs/contracts`, never on a specific cloud
SDK directly.

## Status

`discovery/`, `subsetting/`, `masking/`, `synthetic/`, and `jobs/` remain
structural placeholders — see `problems_master.md` and `ROADMAP.md`
(Phases 7-14) for what's next in each.

`reference_data/` is real, working code: it generates the SYNTHETIC
multi-system healthcare data estate every later phase builds on. See
`src/data_plane/reference_data/README.md` for the full picture and
`docs/tutorial/02-synthetic-data-estate.md` for a walkthrough.

## Layout

```
src/data_plane/
├── reference_data/  # Synthetic multi-system healthcare data estate (real, working)
├── discovery/    # PHI/PII discovery & classification (Phase 7)
├── subsetting/    # Referential-integrity-preserving subsetting (Phase 8)
├── masking/        # Deterministic masking / pseudonymization / tokenization (Phase 9-10)
├── synthetic/       # Synthetic data generation as a masking substitute (Phase 12)
└── jobs/              # Job entry points / DAG-runnable wrappers (Phase 14)
```
