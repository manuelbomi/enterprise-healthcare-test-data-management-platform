"""Top-level orchestration: write a :class:`GeneratedEstate` to all five
simulated source systems and a manifest describing what was produced.

This is the function the CLI (``cli.py``) and the integration tests call.
It is kept separate from ``generator.py`` (which only builds the in-memory
estate) so tests can generate an estate once and either inspect it purely
in memory (fast unit tests) or additionally materialize it to disk
(slower integration tests) without duplicating generation logic.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from data_plane.reference_data.generator import GeneratedEstate
from data_plane.reference_data.writers.adls_writer import write_pbm_extract
from data_plane.reference_data.writers.parquet_writer import write_claims_warehouse
from data_plane.reference_data.writers.partner_writer import write_partner_lab_feed
from data_plane.reference_data.writers.postgres_writer import write_enrollment_system
from data_plane.reference_data.writers.s3_writer import write_clinical_data_lake


@dataclass
class WrittenEstate:
    """Paths/locations everything in a :class:`GeneratedEstate` was written to."""

    output_root: Path
    enrollment_database_url: str
    files_written: list[Path]
    manifest_path: Path


def write_estate(
    estate: GeneratedEstate,
    output_root: Path,
    database_url: str | None = None,
) -> WrittenEstate:
    """Materialize a generated estate across all five simulated source systems."""

    output_root.mkdir(parents=True, exist_ok=True)
    files_written: list[Path] = []

    enrollment_url = write_enrollment_system(
        output_root,
        estate.members,
        estate.demographics,
        estate.addresses,
        estate.plans,
        estate.coverages,
        estate.providers,
        database_url=database_url,
    )

    files_written += write_claims_warehouse(
        output_root, estate.claims, estate.claim_lines, estate.diagnoses, estate.procedures
    )
    files_written += write_clinical_data_lake(output_root, estate.encounters, estate.lab_results)
    files_written += write_pbm_extract(output_root, estate.prescriptions, estate.pharmacies)
    files_written += write_partner_lab_feed(output_root, estate.lab_results)

    manifest_path = output_root / "manifest.json"
    manifest_path.write_text(json.dumps(estate.manifest(), indent=2), encoding="utf-8")

    return WrittenEstate(
        output_root=output_root,
        enrollment_database_url=enrollment_url,
        files_written=files_written,
        manifest_path=manifest_path,
    )


__all__ = ["WrittenEstate", "write_estate"]
