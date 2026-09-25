"""Read the real, on-disk Phase 1 synthetic estate into plain row dicts,
per dataset, across all five simulated source systems.

Mirrors `data_plane.discovery.scanner`'s and
`data_plane.masking.dataset_masker`'s per-source-system function shape
(`read_postgres_enrollment` <-> `scan_postgres_enrollment` <->
`mask_postgres_enrollment`) so all three sibling subpackages read side by
side easily -- discovery figures out what a column *is*, masking decides
what to *do* to a value, and subsetting decides which *rows* survive. All
three walk the exact same five-source-system estate layout independently.

Unlike `discovery.scanner` (which only needs a handful of sample values
per column), subsetting needs every row of every dataset in memory as a
plain ``dict`` (column name -> value), because a subset is selected by
filtering *rows*, not describing columns. Returned rows are plain dicts
(not the Pydantic domain models in `reference_data.domain`) so a row from
any of the five systems -- including columns those domain models don't
know about, e.g. a schema-drifted `amount_paid`/`adjustment_reason_code`
column, or the partner feed's abbreviated `pat_id`/`test_cd` names -- is
carried through unmodified. `data_plane.subsetting.closure` is the module
that actually decides, per dataset, which rows survive.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import cast

import pandas as pd


def _rows_from_dataframe(df: pd.DataFrame) -> list[dict[str, object]]:
    """`DataFrame.to_dict(orient="records")` with pandas NaN normalized to
    `None`, so downstream filtering code never has to special-case NaN."""

    if df.empty:
        return []
    records = df.to_dict(orient="records")
    return [{str(k): (None if pd.isna(v) else v) for k, v in r.items()} for r in records]


@dataclass
class ParquetDataset:
    """A dataset written as one or more Parquet files, optionally
    partitioned into named batches (see `writers/parquet_writer.py`'s
    schema-drifted `claim` batches). ``batches`` preserves the on-disk
    partitioning (batch name -> its own rows, in its own schema) so the
    writer can put each row back in the batch it came from.
    """

    #: batch label (e.g. "claims-2024Q4") -> rows, in that batch's own
    #: on-disk schema. A non-partitioned dataset has a single batch named
    #: "" pointing at `bucket_dir / dataset / "part-0000.parquet"`.
    batches: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def all_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for batch_rows in self.batches.values():
            rows.extend(batch_rows)
        return rows


@dataclass
class PartnerLabFeedData:
    """Raw rows from the partner reference-lab feed, kept split by the two
    file shapes (`writers/partner_writer.py`) and by source file, so the
    writer can reproduce the exact same files (same names, same v1 pipe
    header, same v2 JSON shape) with only a subset of rows.
    """

    #: file name -> (fieldnames in file order, rows as dicts)
    v1_files: dict[str, tuple[list[str], list[dict[str, str]]]] = field(default_factory=dict)
    #: file name -> rows (already dicts, from JSON)
    v2_files: dict[str, list[dict[str, object]]] = field(default_factory=dict)

    def all_rows(self) -> list[dict[str, object]]:
        rows: list[dict[str, object]] = []
        for _fieldnames, v1_rows in self.v1_files.values():
            rows.extend(cast(dict[str, object], dict(r)) for r in v1_rows)
        for v2_rows in self.v2_files.values():
            rows.extend(v2_rows)
        return rows


@dataclass
class RawEstate:
    """Every row of every dataset of a Phase 1 estate, read into memory.

    Field names match the logical dataset names used throughout discovery
    and masking (`member`, `claim`, `lab_result`, ...), not the physical
    file/table names, so downstream code (`closure.py`) can reason about
    entities without caring which of the five source systems they live in.
    """

    member: list[dict[str, object]] = field(default_factory=list)
    member_demographics: list[dict[str, object]] = field(default_factory=list)
    address: list[dict[str, object]] = field(default_factory=list)
    plan: list[dict[str, object]] = field(default_factory=list)
    coverage: list[dict[str, object]] = field(default_factory=list)
    provider: list[dict[str, object]] = field(default_factory=list)
    diagnosis: list[dict[str, object]] = field(default_factory=list)
    procedure: list[dict[str, object]] = field(default_factory=list)
    claim: ParquetDataset = field(default_factory=ParquetDataset)
    claim_line: list[dict[str, object]] = field(default_factory=list)
    pharmacy: list[dict[str, object]] = field(default_factory=list)
    prescription: list[dict[str, object]] = field(default_factory=list)
    encounter: list[dict[str, object]] = field(default_factory=list)
    lab_result_ehr: list[dict[str, object]] = field(default_factory=list)
    lab_result_partner: PartnerLabFeedData = field(default_factory=PartnerLabFeedData)

    def row_counts(self) -> dict[str, int]:
        """Row count per logical entity -- `claim` sums across batches and
        `lab_result` sums the EHR + partner feed, matching
        `GeneratedEstate.row_counts()`'s entity names exactly, so a
        `SubsetManifest.source_counts` is directly comparable to the
        original `manifest.json` a `reference_data.cli` run produced."""

        return {
            "member": len(self.member),
            "member_demographics": len(self.member_demographics),
            "address": len(self.address),
            "plan": len(self.plan),
            "coverage": len(self.coverage),
            "provider": len(self.provider),
            "diagnosis": len(self.diagnosis),
            "procedure": len(self.procedure),
            "claim": len(self.claim.all_rows()),
            "claim_line": len(self.claim_line),
            "pharmacy": len(self.pharmacy),
            "prescription": len(self.prescription),
            "encounter": len(self.encounter),
            "lab_result": len(self.lab_result_ehr) + len(self.lab_result_partner.all_rows()),
        }


def read_postgres_enrollment(sqlite_path: Path) -> dict[str, list[dict[str, object]]]:
    """Read the enrollment SQLite database's six tables (or a real
    Postgres DSN's local stand-in -- see `postgres_models.py`)."""

    tables = ["member", "member_demographics", "address", "plan", "coverage", "provider"]
    result: dict[str, list[dict[str, object]]] = {t: [] for t in tables}
    if not sqlite_path.exists():
        return result

    conn = sqlite3.connect(str(sqlite_path))
    try:
        for table in tables:
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table}", conn)
            except pd.errors.DatabaseError:
                continue
            result[table] = _rows_from_dataframe(df)
    finally:
        conn.close()
    return result


def read_claims_parquet(
    bucket_dir: Path,
) -> tuple[ParquetDataset, list[dict[str, object]], list[dict[str, object]], list[dict[str, object]]]:
    """Read the claims warehouse Parquet extract: `claim` (kept split by
    its schema-drifted batches), `claim_line`, `diagnosis`, `procedure`.
    """

    claim = ParquetDataset()
    claim_line: list[dict[str, object]] = []
    diagnosis: list[dict[str, object]] = []
    procedure: list[dict[str, object]] = []
    if not bucket_dir.exists():
        return claim, claim_line, diagnosis, procedure

    claim_dir = bucket_dir / "claim"
    if claim_dir.exists():
        for batch_dir in sorted(p for p in claim_dir.iterdir() if p.is_dir()):
            batch_name = batch_dir.name.split("=", 1)[-1] if "=" in batch_dir.name else batch_dir.name
            frames = [pd.read_parquet(p) for p in sorted(batch_dir.glob("*.parquet"))]
            if frames:
                claim.batches[batch_name] = _rows_from_dataframe(pd.concat(frames, ignore_index=True, sort=False))

    for dataset, target in (("claim_line", "claim_line"), ("diagnosis", "diagnosis"), ("procedure", "procedure")):
        dataset_dir = bucket_dir / dataset
        if not dataset_dir.exists():
            continue
        frames = [pd.read_parquet(p) for p in sorted(dataset_dir.rglob("*.parquet"))]
        if not frames:
            continue
        rows = _rows_from_dataframe(pd.concat(frames, ignore_index=True, sort=False))
        if target == "claim_line":
            claim_line = rows
        elif target == "diagnosis":
            diagnosis = rows
        else:
            procedure = rows

    return claim, claim_line, diagnosis, procedure


def read_clinical_data_lake(
    bucket_dir: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Read the primary EHR extract: `encounters` and the EHR-sourced
    (`source == "ehr_primary"`) subset of `lab_results`, from NDJSON."""

    encounters: list[dict[str, object]] = []
    lab_results: list[dict[str, object]] = []
    if not bucket_dir.exists():
        return encounters, lab_results

    enc_path = bucket_dir / "encounters" / "part-0000.ndjson"
    if enc_path.exists():
        encounters = [json.loads(line) for line in enc_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    lab_path = bucket_dir / "lab_results" / "part-0000.ndjson"
    if lab_path.exists():
        lab_results = [json.loads(line) for line in lab_path.read_text(encoding="utf-8").splitlines() if line.strip()]

    return encounters, lab_results


def read_pbm_extract(
    container_dir: Path,
) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    """Read the PBM CSV drop: `prescriptions` and `pharmacies`."""

    prescriptions: list[dict[str, object]] = []
    pharmacies: list[dict[str, object]] = []
    if not container_dir.exists():
        return prescriptions, pharmacies

    rx_path = container_dir / "prescriptions" / "part-0000.csv"
    if rx_path.exists() and rx_path.stat().st_size > 0:
        prescriptions = _rows_from_dataframe(pd.read_csv(rx_path, dtype=str))

    pharmacy_path = container_dir / "pharmacies" / "part-0000.csv"
    if pharmacy_path.exists() and pharmacy_path.stat().st_size > 0:
        pharmacies = _rows_from_dataframe(pd.read_csv(pharmacy_path, dtype=str))

    return prescriptions, pharmacies


def read_partner_lab_feed(partner_dir: Path) -> PartnerLabFeedData:
    """Read the partner reference-lab feed: v1 pipe-delimited flat
    file(s) and v2 JSON payload(s), keeping each source file separate so
    the writer can reproduce the exact same file set."""

    data = PartnerLabFeedData()
    inbound = partner_dir / "inbound"
    if not inbound.exists():
        return data

    for v1_path in sorted((inbound / "v1_legacy_flat_file").glob("*.txt")):
        with v1_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            fieldnames = list(reader.fieldnames or [])
            rows = [dict(r) for r in reader]
        data.v1_files[v1_path.name] = (fieldnames, rows)

    for v2_path in sorted((inbound / "v2_api_json").glob("*.json")):
        payload = json.loads(v2_path.read_text(encoding="utf-8"))
        data.v2_files[v2_path.name] = payload if isinstance(payload, list) else []

    return data


def read_estate(estate_root: Path) -> RawEstate:
    """Read every one of the five simulated source systems under
    `estate_root` (the `--out-dir` a `data_plane.reference_data.cli` run
    was written to) into a single in-memory `RawEstate`."""

    estate = RawEstate()
    pg = read_postgres_enrollment(estate_root / "postgres_enrollment" / "enrollment.sqlite3")
    estate.member = pg["member"]
    estate.member_demographics = pg["member_demographics"]
    estate.address = pg["address"]
    estate.plan = pg["plan"]
    estate.coverage = pg["coverage"]
    estate.provider = pg["provider"]

    claim, claim_line, diagnosis, procedure = read_claims_parquet(
        estate_root / "object_storage_claims_parquet" / "claims-warehouse"
    )
    estate.claim = claim
    estate.claim_line = claim_line
    estate.diagnosis = diagnosis
    estate.procedure = procedure

    encounters, ehr_labs = read_clinical_data_lake(estate_root / "s3_clinical_data_lake" / "clinical-data-lake")
    estate.encounter = encounters
    estate.lab_result_ehr = ehr_labs

    prescriptions, pharmacies = read_pbm_extract(estate_root / "adls_pbm_extract" / "pbm-extract")
    estate.prescription = prescriptions
    estate.pharmacy = pharmacies

    estate.lab_result_partner = read_partner_lab_feed(estate_root / "partner_lab_feed")

    return estate


__all__ = [
    "ParquetDataset",
    "PartnerLabFeedData",
    "RawEstate",
    "read_claims_parquet",
    "read_clinical_data_lake",
    "read_estate",
    "read_partner_lab_feed",
    "read_pbm_extract",
    "read_postgres_enrollment",
]
