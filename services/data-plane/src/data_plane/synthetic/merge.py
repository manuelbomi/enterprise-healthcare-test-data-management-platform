"""Merge `ScenarioBatch` output into a `RawEstate`, reusing
`data_plane.subsetting.estate_io.RawEstate` (and, in turn,
`data_plane.subsetting.writer.write_subset_estate` for output) rather
than inventing a parallel read/write path -- exactly the "reuse Phase 4's
estate_io.py/writer.py pattern" the phase brief asks for.

Every plain-list entity (`member`, `coverage`, ...) is a straight
`list.extend`. `claim` is the one exception: `RawEstate.claim` is a
`ParquetDataset` keyed by batch name (mirroring how the real claims
warehouse is partitioned, e.g. `claims-2024Q4`), so every scenario-
generated claim is appended to one dedicated batch,
`provenance.SYNTHETIC_CLAIM_BATCH_NAME` ("synthetic-scenarios") --
itself a form of provenance signal at the batch-name level, consistent
with how this phase's `provenance.py` module justifies tagging at both
the row and batch granularity.
"""

from __future__ import annotations

from data_plane.subsetting.estate_io import RawEstate
from data_plane.synthetic.provenance import SYNTHETIC_CLAIM_BATCH_NAME
from data_plane.synthetic.scenarios import ScenarioBatch

#: ScenarioBatch entity key -> RawEstate list-field name, for every entity
#: a scenario generator can produce EXCEPT `claim` (handled specially,
#: see `merge_scenario_batch`).
_LIST_FIELD_BY_ENTITY = {
    "member": "member",
    "member_demographics": "member_demographics",
    "address": "address",
    "coverage": "coverage",
    "claim_line": "claim_line",
    "prescription": "prescription",
    "encounter": "encounter",
    "lab_result_ehr": "lab_result_ehr",
}


def merge_scenario_batch(estate: RawEstate, batch: ScenarioBatch) -> None:
    """Append every row of `batch` into `estate`, in place."""

    for entity, rows in batch.rows.items():
        if not rows:
            continue
        if entity == "claim":
            estate.claim.batches.setdefault(SYNTHETIC_CLAIM_BATCH_NAME, []).extend(rows)
            continue
        field_name = _LIST_FIELD_BY_ENTITY.get(entity)
        if field_name is None:
            raise ValueError(
                f"Scenario batch {batch.scenario.value!r} produced rows for unrecognized entity "
                f"{entity!r} -- add it to _LIST_FIELD_BY_ENTITY (or the ParquetDataset special-case) "
                "in data_plane.synthetic.merge."
            )
        getattr(estate, field_name).extend(rows)


__all__ = ["merge_scenario_batch"]
