# Chapter 14 — Storage techniques

## The concept

Different kinds of data suit different storage technologies, and a
real enterprise data estate is never stored in just one place or one
format. A transactional enrollment table (members, coverage) wants a
row-oriented OLTP database with real foreign keys and low-latency
single-row reads/writes. A high-volume, append-mostly claims warehouse
wants a columnar, compressible format optimized for scanning many rows
of a few columns. A raw clinical extract landing from an upstream EHR
often arrives as loosely-structured JSON before it's ever curated into
a table at all. Choosing the storage technique to match the *shape and
access pattern* of the data — not using one format for everything — is
itself part of what a TDM platform has to model realistically, because
production estates are heterogeneous and test data that pretends
otherwise won't exercise real integration code paths.

## The five formats this repository actually uses, and why

`data_plane.reference_data/README.md` gives the real reasoning per
source system:

| Entity | Format | Why |
|---|---|---|
| `Member`, `Coverage`, `Plan`, `Provider` | SQLite/PostgreSQL | Transactional, genuinely relational, low volume — the textbook OLTP case ([ADR-0004](../../adr/0004-postgresql-metadata-store.md)) |
| `Claim`, `ClaimLine`, `Diagnosis`, `Procedure` | Parquet | High-volume, append-mostly claims warehouse extract — a textbook columnar workload ([ADR-0007](../../adr/0007-delta-parquet-data-format.md)) |
| `Encounter`, `LabResult` (primary) | NDJSON | A clinical/EHR-style raw "bronze" landing-zone extract — real EHR extracts often land as JSON before curation |
| `Prescription`, `Pharmacy` | CSV | A PBM (pharmacy benefit manager) vendor drop — still very commonly flat CSV in the real world |
| `LabResult` (supplemental) | Legacy flat file + JSON API | A second, independent partner feed, deliberately the messiest, least-controlled shape in the estate |

This is not an arbitrary showcase of "look, we support five formats" —
each choice mirrors a real reason a real enterprise's system would use
that format, and it's what makes Chapters 5-9's discovery/masking code
have to handle real format heterogeneity rather than one convenient
shape.

## Try it yourself: measuring real bytes, not estimating them

`data_plane.capacity.footprint.measure_directory_footprint` reads
actual bytes off actual files — never estimation:

```bash
cd services/data-plane
python -m data_plane.capacity.cli footprint data/tmp/certification-run/final
```

Real output from measuring a real `tiny`-scale certification pipeline's
final output in this environment:

```
Total: 100,680 bytes across 13 file(s)
By extension:
    .parquet:       51,385 bytes (6 file(s))
    .sqlite3:       28,672 bytes (1 file(s))
     .ndjson:       14,365 bytes (2 file(s))
        .csv:        4,058 bytes (2 file(s))
       .json:        2,200 bytes (2 file(s))
  Overall Parquet compression ratio: 0.31x
```

## The honest lesson: Parquet is not "always smaller"

That `0.31x` ratio means Parquet was **larger**, not smaller, than a
plain CSV re-encoding of the same rows at this tiny scale — and that is
a real, measured, reproducible finding, not a mistake to explain away.
`docs/CAPACITY_COST_TRADEOFFS.md` documents this exact tradeoff
honestly: the same measurement code
(`data_plane.capacity.footprint.measure_parquet_compression`) shows
Parquet **losing** to CSV at `tiny` scale (about 0.52x in that
document's own real run — a handful of rows per file), because
Parquet's per-file footer and per-column-chunk statistics are a fixed
overhead a tiny file can't amortize, but shows Parquet **clearly
winning** at `developer` scale (about 1.43x) and `qa` scale (about
3.7x), where there are enough rows per file for columnar compression to
actually pay off. This is the single clearest lesson in this whole
guide about not overclaiming from one measurement: the *same* storage
technique is a good choice or a bad choice depending on real volume —
which is exactly why a real capacity-planning exercise (Chapter 15)
measures at the scale it actually expects to run at, not at whatever
scale is convenient to demo.

## Where to go next

Continue to [Chapter 15 — Capacity planning](15-capacity-planning.md),
or read `docs/tutorial/08-storage-compute-capacity-planning.md` and
`docs/CAPACITY_COST_TRADEOFFS.md` in full for every real measured number
this repository has produced across scale profiles.
