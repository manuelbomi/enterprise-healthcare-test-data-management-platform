"""S3-compatible storage writer: the clinical data lake (EHR extract).

Represents an S3-compatible bucket (MinIO locally / AWS S3 in the cloud —
see ``docs/adr/0005-object-storage-abstraction.md``) holding the primary
EHR extract of ``Encounter`` records and the EHR-sourced (``source =
"ehr_primary"``) subset of ``LabResult`` records. Written as
newline-delimited JSON (NDJSON), the common shape for a raw/bronze
landing zone before it has been curated into a columnar format — a
deliberate contrast with the claims warehouse's Parquet-from-day-one
shape, so the estate is not artificially homogeneous across systems.

The bucket/key layout mirrors what the real MinIO/S3 adapter (Phase 5)
will read from once it exists:
``s3_clinical_data_lake/clinical-data-lake/encounters/part-0000.ndjson``.
"""

from __future__ import annotations

import json
from pathlib import Path

from data_plane.reference_data.domain import Encounter, LabResult

BUCKET = "clinical-data-lake"


def write_clinical_data_lake(
    output_root: Path, encounters: list[Encounter], lab_results: list[LabResult]
) -> list[Path]:
    """Write the primary EHR extract (encounters + EHR-sourced labs) as NDJSON."""

    bucket_dir = output_root / "s3_clinical_data_lake" / BUCKET
    written: list[Path] = []

    encounters_dir = bucket_dir / "encounters"
    encounters_dir.mkdir(parents=True, exist_ok=True)
    encounters_path = encounters_dir / "part-0000.ndjson"
    with encounters_path.open("w", encoding="utf-8") as f:
        for enc in encounters:
            f.write(json.dumps(enc.model_dump()) + "\n")
    written.append(encounters_path)

    primary_labs = [lr for lr in lab_results if lr.source == "ehr_primary"]
    labs_dir = bucket_dir / "lab_results"
    labs_dir.mkdir(parents=True, exist_ok=True)
    labs_path = labs_dir / "part-0000.ndjson"
    with labs_path.open("w", encoding="utf-8") as f:
        for lr in primary_labs:
            f.write(json.dumps(lr.model_dump()) + "\n")
    written.append(labs_path)

    return written


__all__ = ["BUCKET", "write_clinical_data_lake"]
