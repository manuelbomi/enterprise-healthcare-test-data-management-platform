"""Object storage / Parquet writer: the claims data warehouse extract.

Represents a generic (cloud-agnostic) object-storage-backed analytical
extract of the claims subsystem — ``Claim``, ``ClaimLine``, and the
``Diagnosis``/``Procedure`` reference/code tables ``ClaimLine`` joins
against. Written as Parquet, per ``docs/adr/0007-delta-parquet-data-
format.md`` (plain Parquet here: this is a one-shot extract, not a
table the platform updates in place, so Delta's transaction log is not
needed yet).

Schema drift, on purpose
------------------------
``Claim`` rows are written in two batches that intentionally use
*different* schemas, simulating a claims-warehouse ETL change between
quarters:

- ``claim/batch=claims-2024Q4/part-0000.parquet`` — legacy schema, a
  ``paid_amount`` column.
- ``claim/batch=claims-2025Q1/part-0000.parquet`` — current schema,
  ``paid_amount`` renamed to ``amount_paid`` and a new
  ``adjustment_reason_code`` column added.

A consumer that only reads one batch, or that assumes a single fixed
schema across the whole ``claim/`` prefix, will break — which is the
point: this is exactly the kind of drift the discovery/subsetting phases
(Phases 7-8) must be built to tolerate.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from data_plane.reference_data.domain import Claim, ClaimLine, Diagnosis, Procedure

BUCKET = "claims-warehouse"


def _claim_row(claim: Claim, schema: str) -> dict[str, object]:
    row: dict[str, object] = {
        "claim_id": claim.claim_id,
        "member_id": claim.member_id,
        "coverage_id": claim.coverage_id,
        "provider_id": claim.provider_id,
        "claim_type": claim.claim_type,
        "status": claim.status,
        "service_date": claim.service_date,
        "submitted_date": claim.submitted_date,
        "adjudicated_date": claim.adjudicated_date,
        "billed_amount": claim.billed_amount,
        "allowed_amount": claim.allowed_amount,
        "source_extracted_at": claim.source_extracted_at,
        "extract_batch_id": claim.extract_batch_id,
    }
    if schema == "legacy":
        row["paid_amount"] = claim.paid_amount
    else:
        row["amount_paid"] = claim.paid_amount
        row["adjustment_reason_code"] = None
    return row


def write_claims_warehouse(
    output_root: Path,
    claims: list[Claim],
    claim_lines: list[ClaimLine],
    diagnoses: list[Diagnosis],
    procedures: list[Procedure],
) -> list[Path]:
    """Write the claims warehouse extract. Returns the list of files written."""

    bucket_dir = output_root / "object_storage_claims_parquet" / BUCKET
    written: list[Path] = []

    legacy_claims = [c for c in claims if c.extract_batch_id == "claims-2024Q4"]
    current_claims = [c for c in claims if c.extract_batch_id != "claims-2024Q4"]

    if legacy_claims:
        legacy_dir = bucket_dir / "claim" / "batch=claims-2024Q4"
        legacy_dir.mkdir(parents=True, exist_ok=True)
        path = legacy_dir / "part-0000.parquet"
        pd.DataFrame([_claim_row(c, "legacy") for c in legacy_claims]).to_parquet(path, index=False)
        written.append(path)

    if current_claims:
        current_dir = bucket_dir / "claim" / "batch=claims-2025Q1"
        current_dir.mkdir(parents=True, exist_ok=True)
        path = current_dir / "part-0000.parquet"
        pd.DataFrame([_claim_row(c, "current") for c in current_claims]).to_parquet(
            path, index=False
        )
        written.append(path)

    claim_line_dir = bucket_dir / "claim_line"
    claim_line_dir.mkdir(parents=True, exist_ok=True)
    claim_line_path = claim_line_dir / "part-0000.parquet"
    pd.DataFrame([cl.model_dump() for cl in claim_lines]).to_parquet(claim_line_path, index=False)
    written.append(claim_line_path)

    diagnosis_dir = bucket_dir / "diagnosis"
    diagnosis_dir.mkdir(parents=True, exist_ok=True)
    diagnosis_path = diagnosis_dir / "part-0000.parquet"
    pd.DataFrame([d.model_dump() for d in diagnoses]).to_parquet(diagnosis_path, index=False)
    written.append(diagnosis_path)

    procedure_dir = bucket_dir / "procedure"
    procedure_dir.mkdir(parents=True, exist_ok=True)
    procedure_path = procedure_dir / "part-0000.parquet"
    pd.DataFrame([p.model_dump() for p in procedures]).to_parquet(procedure_path, index=False)
    written.append(procedure_path)

    return written


__all__ = ["BUCKET", "write_claims_warehouse"]
