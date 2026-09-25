"""Build the `SyntheticGenerationManifest` (`libs/contracts`) for one
synthetic scenario generation run, and estimate output storage the same
way `data_plane.subsetting.manifest.estimate_storage_bytes` already does
(reused directly rather than reimplemented).
"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID

from healthcare_tdm_contracts import ScenarioGenerationRecord, SyntheticGenerationManifest

from data_plane.subsetting.estate_io import RawEstate
from data_plane.subsetting.manifest import estimate_storage_bytes
from data_plane.synthetic.provenance import DATA_PROVENANCE_FIELD
from data_plane.synthetic.scenarios import ScenarioBatch


def count_provenance(estate: RawEstate) -> dict[str, int]:
    """Row count per `data_provenance` value, across every entity in
    `estate` -- the manifest-level rollup half of this phase's
    belt-and-suspenders provenance guarantee (see `provenance.py`)."""

    counts: dict[str, int] = {}

    def _count(rows: list[dict[str, object]]) -> None:
        for row in rows:
            value = row.get(DATA_PROVENANCE_FIELD)
            if value is None:
                continue
            counts[str(value)] = counts.get(str(value), 0) + 1

    for field_name in (
        "member",
        "member_demographics",
        "address",
        "plan",
        "coverage",
        "provider",
        "diagnosis",
        "procedure",
        "claim_line",
        "pharmacy",
        "prescription",
        "encounter",
        "lab_result_ehr",
    ):
        _count(getattr(estate, field_name))
    for batch_rows in estate.claim.batches.values():
        _count(batch_rows)
    for _fieldnames, rows in estate.lab_result_partner.v1_files.values():
        _count(rows)
    for rows in estate.lab_result_partner.v2_files.values():
        _count(rows)

    return counts


def _resolve_base_subset_manifest_id(base_estate_dir: Path | None) -> UUID | None:
    """If `base_estate_dir` has a `subset_manifest.json` next to it (the
    artifact `data_plane.subsetting` writes -- Phase 4), read its
    `manifest_id` so this run's manifest can trace its lineage back
    through the subsetting run it augmented. Best-effort: returns `None`
    if the file is absent, unreadable, or lacks the field (e.g. the base
    estate was the raw Phase 1 estate, or a masked-only estate with no
    subsetting manifest at all)."""

    if base_estate_dir is None:
        return None
    manifest_path = base_estate_dir / "subset_manifest.json"
    if not manifest_path.exists():
        return None
    try:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        return UUID(data["manifest_id"])
    except (KeyError, ValueError, json.JSONDecodeError):
        return None


def build_manifest(
    *,
    mode: str,
    batches: list[ScenarioBatch],
    estate: RawEstate,
    seed: int,
    base_estate_dir: Path | None,
    out_root: Path,
    version: int = 1,
) -> SyntheticGenerationManifest:
    """Assemble the `SyntheticGenerationManifest` for one generation run."""

    scenario_records = [
        ScenarioGenerationRecord(
            scenario=batch.scenario,
            provenance=batch.provenance,
            description=batch.description,
            row_counts=batch.row_counts(),
            anchor_ids=batch.anchor_ids,
        )
        for batch in batches
    ]

    return SyntheticGenerationManifest(
        version=version,
        mode=mode,
        base_estate_dir=str(base_estate_dir) if base_estate_dir is not None else None,
        base_subset_manifest_id=_resolve_base_subset_manifest_id(base_estate_dir),
        seed=seed,
        scenarios=scenario_records,
        total_row_counts=estate.row_counts(),
        provenance_row_counts=count_provenance(estate),
        estimated_output_storage_bytes=estimate_storage_bytes(out_root),
    )


__all__ = ["build_manifest", "count_provenance"]
