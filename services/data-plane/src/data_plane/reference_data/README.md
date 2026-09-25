# `data_plane.reference_data` — the synthetic healthcare data estate

This package generates a completely **SYNTHETIC** multi-system healthcare
data estate: fake members, coverage, claims, clinical encounters, labs,
prescriptions, and providers, spread across five heterogeneous simulated
source systems. It exists so every later phase of this platform
(discovery, subsetting, masking, snapshotting, the UI) has a realistic,
runnable, non-PHI-bearing estate to operate on instead of hand-authored
fixtures or (never) real data. See `DATA_GOVERNANCE.md` Part A at the
repository root for why synthetic-only data is a hard rule, not a
preference.

This is *not* the same thing as `data_plane.synthetic` (ROADMAP.md Phase
12), which will generate wholly synthetic records *in place of* masking
when no safe source row exists for a scenario. This package generates the
*source-side* estate itself — see the package docstring
(`__init__.py`) for the full distinction.

## Why each dataset exists

| Entity | Source system | Why it lives there |
|---|---|---|
| `Member`, `MemberDemographics`, `Address` | PostgreSQL (`postgres_enrollment`) | Enrollment master data: transactional, genuinely relational, low volume — the textbook case for an OLTP relational database (ADR-0004). `Address` deliberately has no enforced foreign key (see below). |
| `Plan` | PostgreSQL (`postgres_enrollment`) | Small, mostly-static reference vocabulary (product catalog), naturally colocated with the enrollment schema that references it. |
| `Provider` | PostgreSQL (`postgres_enrollment`) | Modeled as a provider *directory* — master data about who renders care, not a claims fact. |
| `Claim`, `ClaimLine` | Object storage / Parquet (`object_storage_claims_parquet`) | High-volume, append-mostly claims warehouse extract — a textbook Parquet/columnar workload (ADR-0007), not something you want as an OLTP write-heavy table. |
| `Diagnosis`, `Procedure` | Object storage / Parquet (`object_storage_claims_parquet`) | Code/reference dimension tables that `ClaimLine` rows join against; shipped alongside the claims warehouse extract because that's where they're consumed. |
| `Encounter`, `LabResult` (primary) | S3-compatible storage (`s3_clinical_data_lake`) | A clinical/EHR-style raw extract, written as NDJSON (a "bronze" landing-zone shape) rather than Parquet, so the estate isn't artificially uniform across systems — real EHR extracts often land as JSON/NDJSON before curation. |
| `Prescription`, `Pharmacy` | Azure/ADLS-compatible storage (`adls_pbm_extract`) | Modeled as a Pharmacy Benefit Manager (PBM) vendor drop — still very commonly flat CSV in the real world. |
| `LabResult` (supplemental) | External partner files/API (`partner_lab_feed`) | A second, independent reference-lab partner sending results for some of the same members (plus some not yet known to enrollment) via a legacy flat file and a modern JSON API shape — the messiest, least-controlled system in the estate, which is realistic for third-party feeds. |

## How referential integrity works

Two different mechanisms are at play, deliberately, because that's how a
real enterprise's data estate actually works (`ARCHITECTURE.md` §3.1):

1. **Within PostgreSQL, referential integrity is real and enforced.**
   `Coverage.member_id -> Member.member_id` and `Coverage.plan_id ->
   Plan.plan_id` are genuine SQLAlchemy `ForeignKey` columns
   (`postgres_models.py`). A real enrollment OLTP database would reject an
   orphaned coverage row, so the generator never tries to create one —
   that would be modeling a database more permissive than the one it's
   supposed to represent. `Address.member_id` is the one deliberate
   exception: it has no enforced foreign key, modeling how address data
   commonly arrives from a separate standardization vendor and gets
   merged in without a hard relationship — which is exactly where the
   generator injects genuine orphan `Address` rows.

2. **Across systems, referential integrity is "soft" — a logical contract
   the generator upholds by construction, not a database constraint.**
   `Claim.member_id`, `Prescription.member_id`, `Encounter.member_id`,
   and the primary `LabResult.member_id` all reference `Member.member_id`
   values from the *same in-memory generation pass* (one `EstateGenerator`
   instance builds every entity in one process, threading IDs through),
   so in the common case a `SYN-MBR-000123` in a claims Parquet file is
   the *same* member as `SYN-MBR-000123` in the enrollment SQLite/Postgres
   database, and joins across systems work — exactly the property
   `docs/adr/0006-deterministic-masking-strategy.md` says later masking
   must preserve. But because nothing enforces this at write time (there
   is no cross-database foreign key spanning Postgres and an S3 bucket —
   that technology doesn't exist), the generator *also* deliberately
   breaks this contract in a controlled, documented fraction of records
   (see below) to give the platform's future discovery/subsetting/masking
   phases real cross-system integrity problems to detect and handle,
   which is this platform's whole reason for existing.

   The five ID namespaces (`SYN-MBR-`, `SYN-PRV-`, `SYN-PLN-`, `SYN-CLM-`,
   `SYN-PHM-`, ...) are unique across the whole estate, so any ID
   collision across two entities is always a real, intentional
   cross-reference, never an accident of formatting.

## Edge cases, and where to find them

All injection rates are configured in `edge_cases.py`
(`EdgeCaseConfig`), and every category is guaranteed to appear **at
least once** even at the `tiny` scale profile (see `_rate_hits` in
`generator.py`) so CI running only the `tiny` profile still exercises
every case.

| Edge case | Where it appears |
|---|---|
| Missing records | Members with no `Coverage` row; `Claim`s with no `ClaimLine` rows |
| Nulls | `date_of_birth`, `middle_name`, address `line1`, and other nullable fields across entities |
| Duplicate records | Duplicate "person" (`Member` re-entered under a new `member_id` with identical demographics — an MDM-style dedup problem); literal duplicate `Claim` rows (re-run extract) — confined to non-Postgres-bound entities, since a real enrollment OLTP database would reject a duplicate primary key |
| Orphan records | Orphan `Address.member_id`; `Claim.member_id`/`Claim.provider_id`; `ClaimLine.claim_id`/`.diagnosis_code`; `Prescription.member_id`; `Encounter.provider_id`; partner `LabResult.member_id` |
| Malformed values | Malformed `zip_code`/`phone`; negative `Claim.paid_amount`/`Prescription.quantity`; non-date strings (`"TBD"`, `"UNKNOWN"`) in `Encounter.discharge_date`; non-numeric `LabResult.result_value` (`"PENDING"`, `">999"`) |
| Late-arriving data | `Claim`/`Encounter` records whose `source_extracted_at` is much later than `service_date`/`admit_date`; partner lab records whose `collected_date` is >90 days before the batch's `delivered_at` (flagged via `late_arrival` in the partner files) |
| Schema drift | Claims Parquet: `claims-2024Q4` batch (`paid_amount` column) vs. `claims-2025Q1` batch (renamed to `amount_paid` + new `adjustment_reason_code` column); partner lab feed: legacy pipe-delimited v1 file (`pat_id`, `test_cd`, ...) vs. current JSON v2 payload (`member_id`, `test_code`, ...) |

The exact counts of everything injected in a given run are recorded in
`manifest.json` (written alongside the generated estate) under the
`edge_cases` key, and are asserted on directly in
`tests/reference_data/test_edge_cases.py`.

## Scale profiles

Four named profiles (`scale.py`): `tiny` (25 members, CI/unit-test
default), `developer` (250 members), `qa` (2,500 members), `performance`
(20,000 members). All other entity counts scale proportionally via
per-member fan-out ratios. See `ScaleProfile.approx_total_rows()` for a
rough total-row estimate per profile.

## Running the generator

```bash
# From services/data-plane, with the package installed (pip install -e .):
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate
```

Output layout under `--out-dir`:

```
postgres_enrollment/enrollment.sqlite3           # Member, MemberDemographics, Address, Plan, Coverage, Provider
object_storage_claims_parquet/claims-warehouse/  # Claim (2 batches), ClaimLine, Diagnosis, Procedure (Parquet)
s3_clinical_data_lake/clinical-data-lake/        # Encounter, LabResult (primary) (NDJSON)
adls_pbm_extract/pbm-extract/                    # Prescription, Pharmacy (CSV)
partner_lab_feed/inbound/                        # LabResult (supplemental): v1 flat file + v2 JSON
manifest.json                                    # row counts + edge-case summary for this run
```

Point `--database-url` at a real PostgreSQL DSN (once
`infra/docker/docker-compose.yml`'s Postgres service is up, Phase 4) to
write the enrollment system there instead of SQLite — the same models and
writer code path handles both (see `postgres_models.py`).
