"""Scan the actual, on-disk Phase 1 synthetic estate and enumerate every
`(source_system, dataset, column)` that really exists, with a handful of
real sample values per column.

This is what makes discovery's output a *real* catalog rather than a
catalog of what the schema says should exist: it reads the five source
systems the same way a real discovery job would — the SQLite-backed
enrollment database, the claims Parquet warehouse (both schema-drifted
batches), the clinical-data-lake NDJSON, the PBM CSV drop, and both
shapes of the partner lab feed (legacy pipe-delimited + current JSON) —
and is therefore the thing that actually catches the schema-drift columns
(`amount_paid`, `adjustment_reason_code`, `pat_id`, `test_cd`, ...) that a
purely schema-based classifier would miss. See `schema_rules.py`'s
docstring and `pattern_rules.py`'s docstring for how those get classified.

Layout scanned (see `reference_data/README.md` for why it's shaped this
way):

    postgres_enrollment/enrollment.sqlite3
    object_storage_claims_parquet/claims-warehouse/{claim,claim_line,diagnosis,procedure}/
    s3_clinical_data_lake/clinical-data-lake/{encounters,lab_results}/
    adls_pbm_extract/pbm-extract/{prescriptions,pharmacies}/
    partner_lab_feed/inbound/{v1_legacy_flat_file,v2_api_json}/

Uses only pandas/pyarrow/sqlite3/json — no Spark session required, mirroring
`data_plane.reference_data`'s own "pandas-compatible path" (see
ARCHITECTURE.md section 2.2). A Spark-backed scan path can be added later
without changing this module's public shape.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pandas as pd

from healthcare_tdm_contracts import SourceSystemType

from data_plane.discovery.engine import ColumnToClassify

_SAMPLE_SIZE = 5


def _samples_from_dataframe(df: pd.DataFrame) -> dict[str, list[str]]:
    samples: dict[str, list[str]] = {}
    for column in df.columns:
        non_null = df[column].dropna().astype(str).head(_SAMPLE_SIZE).tolist()
        samples[str(column)] = non_null
    return samples


def _columns_from_dataframe(
    df: pd.DataFrame, source_system: str, dataset: str, entity: str | None
) -> list[ColumnToClassify]:
    samples = _samples_from_dataframe(df)
    return [
        ColumnToClassify(
            source_system=source_system,
            dataset=dataset,
            entity=entity,
            column=str(column),
            sample_values=samples.get(str(column), []),
        )
        for column in df.columns
    ]


def scan_postgres_enrollment(sqlite_path: Path) -> list[ColumnToClassify]:
    """Scan the enrollment SQLite database (or a real Postgres DSN's local
    stand-in — see `postgres_models.py`) for its six tables."""

    table_to_entity = {
        "member": "Member",
        "member_demographics": "MemberDemographics",
        "address": "Address",
        "plan": "Plan",
        "coverage": "Coverage",
        "provider": "Provider",
    }
    results: list[ColumnToClassify] = []
    if not sqlite_path.exists():
        return results

    conn = sqlite3.connect(str(sqlite_path))
    try:
        for table, entity in table_to_entity.items():
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table} LIMIT 200", conn)
            except pd.errors.DatabaseError:
                continue
            results += _columns_from_dataframe(
                df, SourceSystemType.POSTGRES_ENROLLMENT.value, table, entity
            )
    finally:
        conn.close()
    return results


def scan_claims_parquet(bucket_dir: Path) -> list[ColumnToClassify]:
    """Scan the claims warehouse Parquet extract, unioning the two
    schema-drifted `claim` batches (see `writers/parquet_writer.py`)."""

    entity_by_dataset = {
        "claim": "Claim",
        "claim_line": "ClaimLine",
        "diagnosis": "Diagnosis",
        "procedure": "Procedure",
    }
    results: list[ColumnToClassify] = []
    if not bucket_dir.exists():
        return results

    for dataset, entity in entity_by_dataset.items():
        dataset_dir = bucket_dir / dataset
        if not dataset_dir.exists():
            continue
        frames = [pd.read_parquet(p) for p in sorted(dataset_dir.rglob("*.parquet"))]
        if not frames:
            continue
        df = pd.concat(frames, ignore_index=True, sort=False)
        results += _columns_from_dataframe(
            df, SourceSystemType.OBJECT_STORAGE_CLAIMS_PARQUET.value, dataset, entity
        )
    return results


def scan_clinical_data_lake(bucket_dir: Path) -> list[ColumnToClassify]:
    """Scan the primary EHR extract (encounters + primary lab results),
    written as NDJSON (see `writers/s3_writer.py`)."""

    dataset_to_entity = {"encounters": ("encounter", "Encounter"), "lab_results": ("lab_result", "LabResult")}
    results: list[ColumnToClassify] = []
    if not bucket_dir.exists():
        return results

    for folder, (dataset, entity) in dataset_to_entity.items():
        path = bucket_dir / folder / "part-0000.ndjson"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        if not rows:
            continue
        df = pd.DataFrame(rows)
        results += _columns_from_dataframe(
            df, SourceSystemType.S3_CLINICAL_DATA_LAKE.value, dataset, entity
        )
    return results


def scan_pbm_extract(container_dir: Path) -> list[ColumnToClassify]:
    """Scan the PBM CSV drop (prescriptions + pharmacy directory), see
    `writers/adls_writer.py`."""

    dataset_to_entity = {
        "prescriptions": ("prescription", "Prescription"),
        "pharmacies": ("pharmacy", "Pharmacy"),
    }
    results: list[ColumnToClassify] = []
    if not container_dir.exists():
        return results

    for folder, (dataset, entity) in dataset_to_entity.items():
        path = container_dir / folder / "part-0000.csv"
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_csv(path, dtype=str)
        results += _columns_from_dataframe(df, SourceSystemType.ADLS_PBM_EXTRACT.value, dataset, entity)
    return results


def scan_partner_lab_feed(partner_dir: Path) -> list[ColumnToClassify]:
    """Scan the partner reference-lab feed: v1 pipe-delimited flat file
    (abbreviated field names) and v2 JSON payload, unioned under the same
    logical `lab_result` dataset (see `writers/partner_writer.py` and
    `problems_phase_02.md` P2-3 for why this deliberately does not
    version the two shapes separately)."""

    results: list[ColumnToClassify] = []
    inbound = partner_dir / "inbound"
    if not inbound.exists():
        return results

    v1_rows: list[dict[str, str]] = []
    for v1_path in sorted((inbound / "v1_legacy_flat_file").glob("*.txt")):
        with v1_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            v1_rows.extend(reader)

    v2_rows: list[dict[str, object]] = []
    for v2_path in sorted((inbound / "v2_api_json").glob("*.json")):
        payload = json.loads(v2_path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            v2_rows.extend(payload)

    frames = []
    if v1_rows:
        frames.append(pd.DataFrame(v1_rows))
    if v2_rows:
        frames.append(pd.DataFrame(v2_rows))
    if frames:
        df = pd.concat(frames, ignore_index=True, sort=False)
        results += _columns_from_dataframe(
            df, SourceSystemType.PARTNER_LAB_FEED.value, "lab_result", "LabResult"
        )
    return results


def scan_estate(estate_root: Path) -> list[ColumnToClassify]:
    """Scan every one of the five simulated source systems under
    `estate_root` (the `--out-dir` a `data_plane.reference_data.cli` run
    was written to) and return every discovered column, ready for
    `ClassificationEngine.classify_columns`."""

    columns: list[ColumnToClassify] = []
    columns += scan_postgres_enrollment(estate_root / "postgres_enrollment" / "enrollment.sqlite3")
    columns += scan_claims_parquet(estate_root / "object_storage_claims_parquet" / "claims-warehouse")
    columns += scan_clinical_data_lake(estate_root / "s3_clinical_data_lake" / "clinical-data-lake")
    columns += scan_pbm_extract(estate_root / "adls_pbm_extract" / "pbm-extract")
    columns += scan_partner_lab_feed(estate_root / "partner_lab_feed")
    return columns


__all__ = [
    "scan_claims_parquet",
    "scan_clinical_data_lake",
    "scan_estate",
    "scan_partner_lab_feed",
    "scan_pbm_extract",
    "scan_postgres_enrollment",
]
