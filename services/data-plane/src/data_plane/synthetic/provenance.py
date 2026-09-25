"""Provenance tagging: the mechanism behind this phase's core safety
requirement -- "never allow synthetic records to be mistaken for real
records."

Design decision (documented here because `CONTRIBUTING.md` asks any
consequential, hard-to-reverse decision to be justified where a future
reader will actually look for it): provenance is recorded **both**
per-row and per-batch/manifest, not just one or the other.

- **Per-row** (a ``data_provenance`` column added to every written row,
  across every one of the five simulated source systems' on-disk
  formats): this is the *authoritative* signal, because it survives
  arbitrary downstream filtering/joining/re-sorting of rows -- a
  consumer that reads one row out of context (a single Parquet row group,
  a single NDJSON line pulled into a debugger) can still tell what it is
  without reassembling the whole batch. This matters because this
  phase's own "augment" mode interleaves scenario rows into the *same*
  files/tables the base masked-production-like rows live in (see
  `merge.py`) -- there is no file-level split to rely on for those.
- **Per-batch/manifest** (`SyntheticGenerationManifest.provenance_row_counts`,
  and the ``claim`` entity's dedicated ``synthetic-scenarios`` Parquet
  batch name -- see `merge.py`): this is the fast, human/audit-facing
  summary -- "how much of this output is masked-real vs. fabricated,
  at a glance" -- without reading every row, mirroring how Phase 1
  already names its claim batches by meaning (`claims-2024Q4` /
  `claims-2025Q1`) and Phase 4's `SubsetManifest` already reports
  orphan/injection counts at the manifest level rather than forcing a
  reader to scan every row for them.

Neither one alone is sufficient: per-batch-only provenance breaks the
moment a downstream job re-shuffles rows across batches (nothing stops
that from happening once files leave this pipeline stage); per-row-only
provenance makes a human audit slower than it needs to be. Both together
is the same belt-and-suspenders pattern this codebase already uses for
Phase 4's three-way orphan classification (`closure.py`'s
`DanglingReference.category` *and* `SubsetManifest.known_orphan_counts`).
"""

from __future__ import annotations

from typing import Any

from healthcare_tdm_contracts import DataProvenance, ScenarioType

from data_plane.subsetting.estate_io import RawEstate

#: Column added to every row this phase writes or re-writes.
DATA_PROVENANCE_FIELD = "data_provenance"
#: Column added to every row belonging to a named scenario (absent on
#: supporting reference rows generated only as a prerequisite, and on
#: masked-production-like rows, which by definition are not a "scenario").
SCENARIO_TYPE_FIELD = "scenario_type"
#: Column linking a row back to the generation run that produced it --
#: the `SyntheticGenerationManifest.manifest_id`, as a string.
SYNTHETIC_BATCH_ID_FIELD = "synthetic_batch_id"

#: The Parquet claim-batch name used for every scenario-generated Claim
#: row, deliberately meaningful (mirrors Phase 1's `claims-2024Q4` /
#: `claims-2025Q1` convention) so a reader of the raw claims-warehouse
#: directory listing already sees the provenance split before opening a
#: single file.
SYNTHETIC_CLAIM_BATCH_NAME = "synthetic-scenarios"


def tag_row(
    row: dict[str, Any],
    *,
    provenance: DataProvenance,
    batch_id: str,
    scenario: ScenarioType | None = None,
) -> dict[str, Any]:
    """Return a copy of `row` with provenance columns added.

    Never mutates `row` in place -- callers that build up scenario rows
    from a Pydantic `.model_dump()` should not have to worry about this
    function aliasing their original dict.
    """

    tagged = dict(row)
    tagged[DATA_PROVENANCE_FIELD] = provenance.value
    tagged[SYNTHETIC_BATCH_ID_FIELD] = batch_id
    if scenario is not None:
        tagged[SCENARIO_TYPE_FIELD] = scenario.value
    return tagged


def tag_rows(
    rows: list[dict[str, Any]],
    *,
    provenance: DataProvenance,
    batch_id: str,
    scenario: ScenarioType | None = None,
) -> list[dict[str, Any]]:
    return [tag_row(r, provenance=provenance, batch_id=batch_id, scenario=scenario) for r in rows]


def _tag_in_place(rows: list[dict[str, Any]], *, batch_id: str) -> None:
    """Mutating variant used only for base-estate rows being relabeled
    ``MASKED_PRODUCTION_LIKE`` in place (see
    `tag_base_estate_as_masked_production_like`) -- idempotent: a row
    that already carries a `data_provenance` (e.g. a re-run over output
    this phase already tagged) is left untouched, never overwritten."""

    for row in rows:
        row.setdefault(DATA_PROVENANCE_FIELD, DataProvenance.MASKED_PRODUCTION_LIKE.value)
        row.setdefault(SYNTHETIC_BATCH_ID_FIELD, batch_id)


def tag_base_estate_as_masked_production_like(estate: RawEstate, *, batch_id: str) -> None:
    """Tag every row already present in `estate` (the base
    subsetted-and-masked estate an "augment" run reads) as
    ``MASKED_PRODUCTION_LIKE``, in place.

    This is what makes the per-row provenance guarantee actually hold for
    "augment" mode: once this phase rewrites the estate's files (it must,
    to merge in scenario rows), *every* row in the output -- old and new
    -- carries an explicit, correct provenance tag. Without this step, a
    downstream reader would see `data_provenance` present only on the new
    rows and could reasonably (but wrongly) assume its *absence* means
    "not synthetic" -- exactly the ambiguity this phase must not allow.

    Idempotent: safe to call on an estate this function (or a prior run
    of it) already tagged.
    """

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
        _tag_in_place(getattr(estate, field_name), batch_id=batch_id)

    for batch_rows in estate.claim.batches.values():
        _tag_in_place(batch_rows, batch_id=batch_id)

    partner = estate.lab_result_partner
    for name, (fieldnames, rows) in list(partner.v1_files.items()):
        _tag_in_place(rows, batch_id=batch_id)
        new_fieldnames = list(fieldnames)
        for extra in (DATA_PROVENANCE_FIELD, SYNTHETIC_BATCH_ID_FIELD):
            if extra not in new_fieldnames:
                new_fieldnames.append(extra)
        partner.v1_files[name] = (new_fieldnames, rows)
    for rows in partner.v2_files.values():
        _tag_in_place(rows, batch_id=batch_id)


__all__ = [
    "DATA_PROVENANCE_FIELD",
    "SCENARIO_TYPE_FIELD",
    "SYNTHETIC_BATCH_ID_FIELD",
    "SYNTHETIC_CLAIM_BATCH_NAME",
    "tag_base_estate_as_masked_production_like",
    "tag_row",
    "tag_rows",
]
