"""Write a `RawEstate` subset back to disk, mirroring the exact five-
source-system layout `reference_data.estate_writer.write_estate` and
`masking.dataset_masker.mask_estate` both produce -- so a subset estate is
a drop-in replacement for the full estate for anything (discovery,
masking, a downstream test suite) that only cares about the on-disk shape,
not the row count.

Deliberately mirrors `dataset_masker.py`'s per-source-system function
names and structure (`write_postgres_enrollment` <->
`mask_postgres_enrollment`, etc.) -- masking transforms values and writes
every row back; this module writes back only the *selected* rows,
unmodified.

Design note: a dataset with zero selected rows is skipped entirely
(no file/table is written for it) rather than writing an empty-but-
schema-correct artifact. This mirrors how the original writers already
behave when a batch/dataset is empty (`writers/parquet_writer.py` skips
the `claims-2024Q4` batch directory entirely if no legacy claims exist),
and is called out explicitly in `docs/problems/problems_phase_04.md` as a known,
low-risk limitation (a downstream reader must tolerate a missing
table/file, not assume all fourteen datasets are always present) rather
than silently pretending otherwise.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from pathlib import Path

import pandas as pd

from data_plane.subsetting.estate_io import RawEstate


def write_postgres_enrollment(estate: RawEstate, out_path: Path) -> Path | None:
    tables = {
        "member": estate.member,
        "member_demographics": estate.member_demographics,
        "address": estate.address,
        "plan": estate.plan,
        "coverage": estate.coverage,
        "provider": estate.provider,
    }
    if not any(tables.values()):
        return None

    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path.unlink()
    conn = sqlite3.connect(str(out_path))
    try:
        for table, rows in tables.items():
            if not rows:
                continue
            pd.DataFrame(rows).to_sql(table, conn, index=False, if_exists="replace")
        conn.commit()
    finally:
        conn.close()
    return out_path


def write_claims_parquet(estate: RawEstate, bucket_dir: Path) -> list[Path]:
    written: list[Path] = []

    for batch, rows in estate.claim.batches.items():
        if not rows:
            continue
        batch_dir = bucket_dir / "claim" / f"batch={batch}"
        batch_dir.mkdir(parents=True, exist_ok=True)
        path = batch_dir / "part-0000.parquet"
        pd.DataFrame(rows).to_parquet(path, index=False)
        written.append(path)

    for dataset, rows in (
        ("claim_line", estate.claim_line),
        ("diagnosis", estate.diagnosis),
        ("procedure", estate.procedure),
    ):
        if not rows:
            continue
        dataset_dir = bucket_dir / dataset
        dataset_dir.mkdir(parents=True, exist_ok=True)
        path = dataset_dir / "part-0000.parquet"
        pd.DataFrame(rows).to_parquet(path, index=False)
        written.append(path)

    return written


def write_clinical_data_lake(estate: RawEstate, bucket_dir: Path) -> list[Path]:
    written: list[Path] = []

    if estate.encounter:
        path = bucket_dir / "encounters" / "part-0000.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in estate.encounter:
                f.write(json.dumps(row) + "\n")
        written.append(path)

    if estate.lab_result_ehr:
        path = bucket_dir / "lab_results" / "part-0000.ndjson"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as f:
            for row in estate.lab_result_ehr:
                f.write(json.dumps(row) + "\n")
        written.append(path)

    return written


def write_pbm_extract(estate: RawEstate, container_dir: Path) -> list[Path]:
    written: list[Path] = []

    for dataset, rows in (("prescriptions", estate.prescription), ("pharmacies", estate.pharmacy)):
        if not rows:
            continue
        path = container_dir / dataset / "part-0000.csv"
        path.parent.mkdir(parents=True, exist_ok=True)
        fieldnames = list(rows[0].keys())
        with path.open("w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
        written.append(path)

    return written


def write_partner_lab_feed(estate: RawEstate, partner_dir: Path) -> list[Path]:
    written: list[Path] = []
    partner = estate.lab_result_partner

    for name, (fieldnames, v1_rows) in partner.v1_files.items():
        if not v1_rows:
            continue
        path = partner_dir / "inbound" / "v1_legacy_flat_file" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8", newline="") as f:
            f.write("|".join(fieldnames) + "\n")
            for row in v1_rows:
                f.write("|".join(str(row.get(col, "") or "") for col in fieldnames) + "\n")
        written.append(path)

    for name, v2_rows in partner.v2_files.items():
        if not v2_rows:
            continue
        path = partner_dir / "inbound" / "v2_api_json" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(v2_rows, indent=2), encoding="utf-8")
        written.append(path)

    return written


def write_subset_estate(estate: RawEstate, out_root: Path) -> list[Path]:
    """Write every selected row of `estate` to `out_root`, mirroring the
    layout `reference_data.estate_writer.write_estate` uses for the full
    estate. Returns the list of files/databases written."""

    written: list[Path] = []

    pg_path = write_postgres_enrollment(estate, out_root / "postgres_enrollment" / "enrollment.sqlite3")
    if pg_path is not None:
        written.append(pg_path)

    written += write_claims_parquet(estate, out_root / "object_storage_claims_parquet" / "claims-warehouse")
    written += write_clinical_data_lake(estate, out_root / "s3_clinical_data_lake" / "clinical-data-lake")
    written += write_pbm_extract(estate, out_root / "adls_pbm_extract" / "pbm-extract")
    written += write_partner_lab_feed(estate, out_root / "partner_lab_feed")

    return written


__all__ = [
    "write_claims_parquet",
    "write_clinical_data_lake",
    "write_partner_lab_feed",
    "write_pbm_extract",
    "write_postgres_enrollment",
    "write_subset_estate",
]
