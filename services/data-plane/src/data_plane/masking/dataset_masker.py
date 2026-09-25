"""Apply the masking engine to the real, on-disk Phase 1 synthetic estate,
using the real Phase 2 catalog to decide which technique masks which
column.

This is the "catalog classification -> masking policy -> masked output"
integration point `ARCHITECTURE.md` section 2.2 describes for the data
plane's `Masking` component, and it deliberately mirrors
`data_plane.discovery.scanner`'s per-source-system function shape
(`mask_postgres_enrollment` <-> `scan_postgres_enrollment`, etc.) so the
two packages read side by side easily -- discovery figures out what a
column *is*, masking decides what to *do* about it, and both walk the
exact same five-source-system estate layout independently (this module
does not import `discovery` at runtime; it consumes the same
`CatalogEntry` shape `discovery.catalog_builder.write_catalog` already
produced -- see `docs/adr/0009-catalog-artifact-handoff.md`'s
plane-separation reasoning, which applies just as well within the data
plane between these two sibling subpackages).

Every masked output file lives at the same relative path under a new
output root as its unmasked counterpart under the estate root, so a
masked estate is a drop-in replacement for the original for anything that
only cares about referential shape, not real values.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pandas as pd

from healthcare_tdm_contracts import CatalogEntry, MaskingPolicy

from data_plane.masking.engine import MaskingEngine, MaskingWarning
from data_plane.masking.policy import DEFAULT_POLICY, resolve_rule


@dataclass
class MaskingRunReport:
    """Summary of one `mask_estate` run -- printed by the CLI and used by
    `validation.py`/tests to check the run actually did what it claims.
    """

    rows_processed: int = 0
    columns_masked: int = 0
    technique_counts: dict[str, int] = field(default_factory=dict)
    files_written: list[Path] = field(default_factory=list)
    warnings: list[MaskingWarning] = field(default_factory=list)
    #: (source_system, dataset, column) -> {original_value: masked_value},
    #: kept ONLY for columns with preserve_linkage=True, and only up to a
    #: small cap, so validation/tests can check cross-system consistency
    #: without holding the whole estate's value space in memory.
    linkage_samples: dict[tuple[str, str, str], dict[str, str]] = field(default_factory=dict)

    def record(self, technique_value: str) -> None:
        self.columns_masked += 1
        self.technique_counts[technique_value] = self.technique_counts.get(technique_value, 0) + 1


_LINKAGE_SAMPLE_CAP = 50


class CatalogLookup:
    """`(source_system, dataset, column) -> CatalogEntry`, built once per
    run from the catalog artifact `discovery.cli` produced."""

    def __init__(self, entries: list[CatalogEntry]) -> None:
        self._by_key: dict[tuple[str, str, str], CatalogEntry] = {
            (e.source, e.dataset, e.column): e for e in entries
        }

    def get(self, source_system: str, dataset: str, column: str) -> CatalogEntry | None:
        return self._by_key.get((source_system, dataset, column))


def mask_row_dict(
    row: dict[str, Any],
    *,
    source_system: str,
    dataset: str,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> dict[str, Any]:
    """Mask every present key of `row` using the catalog's classification
    for `(source_system, dataset, column)`.

    A column present in the row but absent from the catalog (should not
    happen against a catalog produced by a discovery run over the same
    estate, but defensive against drift) falls back to the conservative
    `HMAC_PSEUDONYMIZATION` technique rather than passing the raw value
    through -- consistent with `DATA_GOVERNANCE.md` B.1's "never default
    an unknown column to safe."
    """

    from healthcare_tdm_contracts import MaskingFieldType, MaskingTechnique

    masked: dict[str, Any] = {}
    for column, value in row.items():
        entry = catalog.get(source_system, dataset, column)
        if entry is None:
            digest_scope = f"unclassified:{source_system}:{dataset}:{column}"
            masked[column] = engine.mask_value(
                value,
                technique=MaskingTechnique.HMAC_PSEUDONYMIZATION,
                scope=digest_scope,
                field_type=MaskingFieldType.GENERIC,
            )
            report.record(MaskingTechnique.HMAC_PSEUDONYMIZATION.value)
            continue

        resolved = resolve_rule(policy, tier=entry.classification.tier, column=column)
        masked_value = engine.mask_value(
            value,
            technique=resolved.technique,
            scope=resolved.scope,
            field_type=resolved.field_type,
            preserve_format=resolved.preserve_format,
            preserve_null=resolved.preserve_null,
            parameters=resolved.parameters,
        )
        masked[column] = masked_value
        report.record(resolved.technique.value)

        if resolved.preserve_linkage and value is not None:
            key = (source_system, dataset, column)
            samples = report.linkage_samples.setdefault(key, {})
            if len(samples) < _LINKAGE_SAMPLE_CAP:
                samples[str(value)] = str(masked_value)

    return masked


def _mask_dataframe(
    df: pd.DataFrame,
    *,
    source_system: str,
    dataset: str,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> pd.DataFrame:
    if df.empty:
        return df
    records = df.to_dict(orient="records")
    masked_records = [
        mask_row_dict(
            {k: (None if pd.isna(v) else v) for k, v in r.items()},
            source_system=source_system,
            dataset=dataset,
            catalog=catalog,
            engine=engine,
            policy=policy,
            report=report,
        )
        for r in records
    ]
    report.rows_processed += len(masked_records)
    return pd.DataFrame(masked_records, columns=df.columns)


# ---------------------------------------------------------------------------
# Per-source-system maskers (mirrors discovery/scanner.py's shape).
# ---------------------------------------------------------------------------


def mask_postgres_enrollment(
    sqlite_in: Path,
    sqlite_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not sqlite_in.exists():
        return
    sqlite_out.parent.mkdir(parents=True, exist_ok=True)
    if sqlite_out.exists():
        sqlite_out.unlink()

    table_to_dataset = {
        "member": "member",
        "member_demographics": "member_demographics",
        "address": "address",
        "plan": "plan",
        "coverage": "coverage",
        "provider": "provider",
    }
    source_conn = sqlite3.connect(str(sqlite_in))
    out_conn = sqlite3.connect(str(sqlite_out))
    try:
        for table, dataset in table_to_dataset.items():
            try:
                df = pd.read_sql_query(f"SELECT * FROM {table}", source_conn)
            except pd.errors.DatabaseError:
                continue
            masked = _mask_dataframe(
                df,
                source_system="postgres_enrollment",
                dataset=dataset,
                catalog=catalog,
                engine=engine,
                policy=policy,
                report=report,
            )
            masked.to_sql(table, out_conn, index=False, if_exists="replace")
        out_conn.commit()
    finally:
        source_conn.close()
        out_conn.close()
    report.files_written.append(sqlite_out)


def mask_claims_parquet(
    bucket_in: Path,
    bucket_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not bucket_in.exists():
        return
    entity_datasets = {"claim", "claim_line", "diagnosis", "procedure"}
    for dataset in entity_datasets:
        dataset_dir = bucket_in / dataset
        if not dataset_dir.exists():
            continue
        for parquet_path in sorted(dataset_dir.rglob("*.parquet")):
            relative = parquet_path.relative_to(bucket_in)
            out_path = bucket_out / relative
            out_path.parent.mkdir(parents=True, exist_ok=True)
            df = pd.read_parquet(parquet_path)
            masked = _mask_dataframe(
                df,
                source_system="object_storage_claims_parquet",
                dataset=dataset,
                catalog=catalog,
                engine=engine,
                policy=policy,
                report=report,
            )
            masked.to_parquet(out_path, index=False)
            report.files_written.append(out_path)


def mask_clinical_data_lake(
    bucket_in: Path,
    bucket_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not bucket_in.exists():
        return
    for folder, dataset in (("encounters", "encounter"), ("lab_results", "lab_result")):
        path = bucket_in / folder / "part-0000.ndjson"
        if not path.exists():
            continue
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        out_path = bucket_out / folder / "part-0000.ndjson"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8") as f:
            for row in rows:
                masked = mask_row_dict(
                    row,
                    source_system="s3_clinical_data_lake",
                    dataset=dataset,
                    catalog=catalog,
                    engine=engine,
                    policy=policy,
                    report=report,
                )
                f.write(json.dumps(masked) + "\n")
                report.rows_processed += 1
        report.files_written.append(out_path)


def mask_pbm_extract(
    container_in: Path,
    container_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    if not container_in.exists():
        return
    for folder, dataset in (("prescriptions", "prescription"), ("pharmacies", "pharmacy")):
        path = container_in / folder / "part-0000.csv"
        if not path.exists() or path.stat().st_size == 0:
            continue
        df = pd.read_csv(path, dtype=str)
        masked = _mask_dataframe(
            df,
            source_system="adls_pbm_extract",
            dataset=dataset,
            catalog=catalog,
            engine=engine,
            policy=policy,
            report=report,
        )
        out_path = container_out / folder / "part-0000.csv"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        masked.to_csv(out_path, index=False)
        report.files_written.append(out_path)


def mask_partner_lab_feed(
    partner_in: Path,
    partner_out: Path,
    *,
    catalog: CatalogLookup,
    engine: MaskingEngine,
    policy: MaskingPolicy,
    report: MaskingRunReport,
) -> None:
    inbound_in = partner_in / "inbound"
    if not inbound_in.exists():
        return

    for v1_path in sorted((inbound_in / "v1_legacy_flat_file").glob("*.txt")):
        with v1_path.open(encoding="utf-8") as f:
            reader = csv.DictReader(f, delimiter="|")
            fieldnames = reader.fieldnames or []
            rows = list(reader)
        out_path = partner_out / "inbound" / "v1_legacy_flat_file" / v1_path.name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open("w", encoding="utf-8", newline="") as f:
            f.write("|".join(fieldnames) + "\n")
            for row in rows:
                masked = mask_row_dict(
                    dict(row),
                    source_system="partner_lab_feed",
                    dataset="lab_result",
                    catalog=catalog,
                    engine=engine,
                    policy=policy,
                    report=report,
                )
                f.write("|".join(str(masked.get(col, "") or "") for col in fieldnames) + "\n")
                report.rows_processed += 1
        report.files_written.append(out_path)

    for v2_path in sorted((inbound_in / "v2_api_json").glob("*.json")):
        payload = json.loads(v2_path.read_text(encoding="utf-8"))
        rows = payload if isinstance(payload, list) else []
        masked_rows = [
            mask_row_dict(
                row,
                source_system="partner_lab_feed",
                dataset="lab_result",
                catalog=catalog,
                engine=engine,
                policy=policy,
                report=report,
            )
            for row in rows
        ]
        report.rows_processed += len(masked_rows)
        out_path = partner_out / "inbound" / "v2_api_json" / v2_path.name
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps(masked_rows, indent=2), encoding="utf-8")
        report.files_written.append(out_path)


def mask_estate(
    estate_root: Path,
    catalog_entries: list[CatalogEntry],
    out_root: Path,
    engine: MaskingEngine,
    *,
    policy: MaskingPolicy | None = None,
) -> MaskingRunReport:
    """Mask every one of the five simulated source systems under
    `estate_root`, writing the masked estate to `out_root` (mirroring the
    same relative layout `reference_data.estate_writer.write_estate`
    produced), using `catalog_entries` (the real Phase 2 discovery output)
    to decide which technique masks which column.
    """

    policy = policy or DEFAULT_POLICY
    catalog = CatalogLookup(catalog_entries)
    report = MaskingRunReport()

    mask_postgres_enrollment(
        estate_root / "postgres_enrollment" / "enrollment.sqlite3",
        out_root / "postgres_enrollment" / "enrollment.sqlite3",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_claims_parquet(
        estate_root / "object_storage_claims_parquet" / "claims-warehouse",
        out_root / "object_storage_claims_parquet" / "claims-warehouse",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_clinical_data_lake(
        estate_root / "s3_clinical_data_lake" / "clinical-data-lake",
        out_root / "s3_clinical_data_lake" / "clinical-data-lake",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_pbm_extract(
        estate_root / "adls_pbm_extract" / "pbm-extract",
        out_root / "adls_pbm_extract" / "pbm-extract",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )
    mask_partner_lab_feed(
        estate_root / "partner_lab_feed",
        out_root / "partner_lab_feed",
        catalog=catalog,
        engine=engine,
        policy=policy,
        report=report,
    )

    report.warnings = list(engine.warnings)
    return report


__all__ = [
    "CatalogLookup",
    "MaskingRunReport",
    "mask_claims_parquet",
    "mask_clinical_data_lake",
    "mask_estate",
    "mask_pbm_extract",
    "mask_partner_lab_feed",
    "mask_postgres_enrollment",
    "mask_row_dict",
]
