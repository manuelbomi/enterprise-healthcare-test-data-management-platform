"""Build a `SubsetManifest` (`libs/contracts`) from the output of one
subsetting run: what was asked for (`selection.SelectionResult`), what the
referential-closure graph walk produced (`closure.ClosureResult`), and
whether it validated clean (`validation.SubsetValidationReport`).

This is the single place all of that gets assembled into the durable,
typed record the phase's spec asks for: source counts, selected
counts, relationship counts, filter criteria, timestamp, version,
estimated storage, integrity status.
"""

from __future__ import annotations

from pathlib import Path

from healthcare_tdm_contracts import SubsetManifest, SubsetSelectionCriteria, SubsettingStrategy

from data_plane.subsetting.closure import ClosureResult
from data_plane.subsetting.estate_io import RawEstate
from data_plane.subsetting.selection import SelectionResult
from data_plane.subsetting.validation import SubsetValidationReport


def estimate_storage_bytes(root: Path) -> int:
    """Sum the size of every file under `root`, recursively. Used for both
    `estimated_source_storage_bytes` (the estate this subset was drawn
    from) and `estimated_subset_storage_bytes` (what was actually
    written) -- a real, on-disk measurement, not a row-count heuristic.
    """

    if not root.exists():
        return 0
    return sum(p.stat().st_size for p in root.rglob("*") if p.is_file())


def build_manifest(
    *,
    scale_profile: str,
    source_estate: RawEstate,
    closure: ClosureResult,
    selection: SelectionResult,
    strategy: SubsettingStrategy,
    validation: SubsetValidationReport,
    negative_testing: bool,
    estate_root: Path,
    out_root: Path,
    version: int = 1,
) -> SubsetManifest:
    """Assemble the `SubsetManifest` for one subsetting run."""

    criteria = SubsetSelectionCriteria(
        strategy=strategy,
        parameters=selection.resolved_parameters,
        description=selection.description,
        negative_testing=negative_testing,
    )

    filter_criteria = dict(selection.resolved_parameters)
    filter_criteria["anchor_selected_count"] = str(len(selection.member_ids))

    return SubsetManifest(
        version=version,
        scale_profile=scale_profile,
        selection=criteria,
        source_counts=source_estate.row_counts(),
        selected_counts=closure.selected.row_counts(),
        relationship_edges=closure.edges,
        filter_criteria=filter_criteria,
        estimated_source_storage_bytes=estimate_storage_bytes(estate_root),
        estimated_subset_storage_bytes=estimate_storage_bytes(out_root),
        integrity_status=validation.status,
        known_orphan_counts=validation.known_orphan_counts,
        injected_negative_test_orphan_counts=validation.injected_negative_test_orphan_counts,
        integrity_findings=validation.findings,
    )


__all__ = ["build_manifest", "estimate_storage_bytes"]
