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
`certification/`, `capacity/`, `spark/`, and `benchmarks/` are all real,
working code, implemented in Phases 1-6, 8, and 14 respectively — each
has its own README with a full module map and worked examples. `jobs/`
remains a structural placeholder: none of the above are yet submitted as
control-plane-orchestrated jobs (each has its own standalone CLI
instead) — see `docs/problems/problems_master.md` and `docs/problems/problems_phase_06.md` P6-1.
**Correction to this file's own earlier text**: this line used to point
at "`ROADMAP.md` Phase 14" as where that gap would close; Phase 14's
actual scope turned out to be scale/performance benchmark tooling (real
PySpark jobs + a benchmark harness), not job-orchestration wiring — see
`docs/problems/problems_phase_14.md` P14-4, which keeps this exact gap open for the
Spark jobs too, rather than re-promising a later phase that has not
actually scoped it yet.

| Package | Phase | What it does |
|---|---|---|
| `reference_data/` | 1 | Generates the SYNTHETIC multi-system healthcare data estate every later phase builds on. |
| `discovery/` | 2 | PHI/PII discovery and classification; produces the data catalog. |
| `masking/` | 3 | Policy-driven, deterministic masking/pseudonymization/tokenization. |
| `subsetting/` | 4 | Referential-integrity-preserving population subsetting. |
| `synthetic/` | 5 | Optional synthetic test-scenario generation, layered on top of a masked/subsetted estate. |
| `certification/` | 6 | Orchestrates all of the above end to end and adds VALIDATE/CERTIFY/PUBLISH — see `src/data_plane/certification/README.md` and `docs/CERTIFICATION_VS_MASKING.md`. |
| `capacity/` | 8 | Real, on-disk footprint measurement (compression, partitioning) — the data-plane half of capacity planning; see `src/data_plane/capacity/README.md` and `docs/CAPACITY_COST_TRADEOFFS.md`. |
| `spark/` | 14 | Real, `local[*]` PySpark jobs (masking via `pandas_udf`, subsetting via broadcast join) — see `src/data_plane/spark/README.md` and `docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md`. |
| `benchmarks/` | 14 | Real benchmark tooling measuring records/sec, masking/subsetting throughput, storage footprint, and compression ratio — see `src/data_plane/benchmarks/README.md` and `docs/SCALE_AND_PERFORMANCE.md`. |

## Layout

```
src/data_plane/
├── reference_data/  # Synthetic multi-system healthcare data estate (Phase 1)
├── discovery/       # PHI/PII discovery & classification (Phase 2)
├── masking/         # Deterministic masking / pseudonymization / tokenization (Phase 3)
├── subsetting/      # Referential-integrity-preserving subsetting (Phase 4)
├── synthetic/        # Optional synthetic scenario generation (Phase 5)
├── certification/    # Certified test dataset pipeline: VALIDATE -> CERTIFY -> PUBLISH (Phase 6)
├── capacity/          # Real, on-disk footprint measurement (Phase 8)
├── spark/             # Real local-mode PySpark masking/subsetting jobs (Phase 14)
├── benchmarks/         # Real scale/performance benchmark harness (Phase 14)
└── jobs/              # Job entry points / DAG-runnable wrappers (still a placeholder)
```
