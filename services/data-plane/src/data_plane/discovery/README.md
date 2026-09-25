# `data_plane.discovery` — PHI/PII discovery and classification (Phase 2)

Classifies every column of every dataset in the Phase 1 synthetic estate
(`data_plane.reference_data`) into a `SensitivityCategory`
(`direct_identifier` / `quasi_identifier` / `phi` / `pii` / `sensitive` /
`non_sensitive`) and a masking-policy `ClassificationTier`, using
schema-based rules, rule-based (pattern) detectors, and manual overrides
— see `libs/contracts/src/healthcare_tdm_contracts/classification.py` for
the full contract and `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for
what this can and cannot prove. **Read that document before trusting this
engine's output for anything beyond triage.**

## Module map

| Module | Responsibility |
|---|---|
| `schema_rules.py` | Authoritative, human-authored classification for every field of all 14 Phase 1 entities. Confidence 1.0. |
| `pattern_rules.py` | Column-name (and, for two detectors, sample-value) regex heuristics, consulted only when the schema layer doesn't recognize a column. |
| `overrides.py` + `manual_overrides.yaml` | Steward-authored corrections, highest precedence, confidence 1.0, always signed with a `confirmed_by` identity. |
| `engine.py` | `ClassificationEngine`: combines the three layers above with the documented precedence (override > schema > pattern > conservative default) and DATA_GOVERNANCE.md B.1's conservative-default rule. |
| `scanner.py` | Reads the *actual* generated Phase 1 estate on disk (SQLite, Parquet, NDJSON, CSV, partner flat-file/JSON) and enumerates real `(source_system, dataset, column)` triples with sample values. |
| `catalog_builder.py` | Turns classified columns into full `CatalogEntry` rows (+ masking requirement, owner, retention classification) and reads/writes the catalog as a JSON artifact. |
| `cli.py` | Command-line entry point. |

## Running it

```bash
# From services/data-plane, with the package installed (pip install -e .):

# 1. Generate a synthetic estate (Phase 1 CLI) if you don't have one yet:
python -m data_plane.reference_data.cli --scale tiny --out-dir data/tmp/synthetic-estate

# 2. Run discovery against it:
python -m data_plane.discovery.cli --estate-dir data/tmp/synthetic-estate \
    --out data/tmp/synthetic-estate/catalog.json
```

This prints a per-category breakdown and how many columns are flagged for
data-steward review (confidence below 0.7 and unconfirmed), then writes
`catalog.json` — an array of `CatalogEntry` objects (see
`libs/contracts/src/healthcare_tdm_contracts/catalog.py`).

Point the control plane's `TDM_CONTROL_PLANE_CATALOG_PATH` environment
variable at the resulting file to serve it over
`GET /api/v1/catalog` (see `services/control-plane/src/control_plane/api/v1/catalog.py`
and `docs/adr/0009-catalog-artifact-handoff.md` for why this is a file
handoff rather than a direct database write in this phase).

## Why the classification is per-(entity, column), not per-column-name

The same column name can mean different things on different entities.
`Diagnosis.diagnosis_code` (a free-standing code-vocabulary row — the
definition of an ICD-style code reveals nothing about any specific
person) is `non_sensitive`; `ClaimLine.diagnosis_code` (a specific code
value attached, via `claim_id`, to a specific member's specific claim) is
`phi`. `schema_rules.py` is keyed by `(entity, column)` precisely so this
distinction survives.

## Why some columns are only caught by the pattern layer

`writers/parquet_writer.py`'s claims-warehouse schema drift renames
`paid_amount` to `amount_paid` and adds `adjustment_reason_code` in the
current-quarter batch; `writers/partner_writer.py`'s legacy v1 lab feed
uses abbreviated field names (`pat_id`, `test_cd`, `test_nm`, `result`,
`collected_dt`). None of these on-disk names are literal fields of the
Phase 1 domain models, so the schema layer never recognizes them — this
is the schema-drift edge case working as intended (see
`reference_data/README.md`'s "Edge cases" table), and it's exactly what
the pattern layer (and, for `adjustment_reason_code`, a manual override —
see `manual_overrides.yaml`) exists to catch.
`services/data-plane/tests/discovery/test_scanner_against_real_estate.py`
generates a real estate and asserts every one of these columns is found
and correctly classified end to end.
