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

`reference_data/`, `discovery/`, `masking/`, `subsetting/`, `synthetic/`,
and `certification/` are all real, working code, implemented in Phases
1-6 respectively — each has its own README with a full module map and
worked examples. `jobs/` remains a structural placeholder: none of the
above are yet submitted as control-plane-orchestrated jobs (each has its
own standalone CLI instead) — see `problems_master.md`,
`problems_phase_06.md` P6-1, and `ROADMAP.md` Phase 14.

| Package | Phase | What it does |
|---|---|---|
| `reference_data/` | 1 | Generates the SYNTHETIC multi-system healthcare data estate every later phase builds on. |
| `discovery/` | 2 | PHI/PII discovery and classification; produces the data catalog. |
| `masking/` | 3 | Policy-driven, deterministic masking/pseudonymization/tokenization. |
| `subsetting/` | 4 | Referential-integrity-preserving population subsetting. |
| `synthetic/` | 5 | Optional synthetic test-scenario generation, layered on top of a masked/subsetted estate. |
| `certification/` | 6 | Orchestrates all of the above end to end and adds VALIDATE/CERTIFY/PUBLISH — see `src/data_plane/certification/README.md` and `docs/CERTIFICATION_VS_MASKING.md`. |

## Layout

```
src/data_plane/
├── reference_data/  # Synthetic multi-system healthcare data estate (Phase 1)
├── discovery/       # PHI/PII discovery & classification (Phase 2)
├── masking/         # Deterministic masking / pseudonymization / tokenization (Phase 3)
├── subsetting/      # Referential-integrity-preserving subsetting (Phase 4)
├── synthetic/        # Optional synthetic scenario generation (Phase 5)
├── certification/    # Certified test dataset pipeline: VALIDATE -> CERTIFY -> PUBLISH (Phase 6)
└── jobs/              # Job entry points / DAG-runnable wrappers (Phase 14)
```
