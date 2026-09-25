"""Azure/ADLS-compatible writer: the pharmacy benefit manager (PBM) extract.

Represents an Azure Blob/ADLS container (see ``docs/adr/0005-object-
storage-abstraction.md``) holding a vendor-style CSV drop of
``Prescription`` and ``Pharmacy`` records, as a PBM would deliver to a
health plan. CSV rather than Parquet/NDJSON on purpose: vendor file
drops in this space are still very commonly flat CSV, and using a third
format here (after Parquet and NDJSON) keeps the estate genuinely
heterogeneous across all five simulated source systems, per the Phase 1
promptbook's requirement.
"""

from __future__ import annotations

import csv
from pathlib import Path

from data_plane.reference_data.domain import Pharmacy, Prescription

CONTAINER = "pbm-extract"


def write_pbm_extract(
    output_root: Path, prescriptions: list[Prescription], pharmacies: list[Pharmacy]
) -> list[Path]:
    """Write the PBM extract (prescriptions + pharmacy directory) as CSV."""

    container_dir = output_root / "adls_pbm_extract" / CONTAINER
    written: list[Path] = []

    rx_dir = container_dir / "prescriptions"
    rx_dir.mkdir(parents=True, exist_ok=True)
    rx_path = rx_dir / "part-0000.csv"
    _write_csv(rx_path, [rx.model_dump() for rx in prescriptions])
    written.append(rx_path)

    pharmacy_dir = container_dir / "pharmacies"
    pharmacy_dir.mkdir(parents=True, exist_ok=True)
    pharmacy_path = pharmacy_dir / "part-0000.csv"
    _write_csv(pharmacy_path, [p.model_dump() for p in pharmacies])
    written.append(pharmacy_path)

    return written


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames = list(rows[0].keys())
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


__all__ = ["CONTAINER", "write_pbm_extract"]
