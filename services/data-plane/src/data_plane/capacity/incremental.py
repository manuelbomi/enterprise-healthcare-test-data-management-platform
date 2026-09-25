"""Incremental-refresh savings modeling (Phase 8).

Phase 7's `LifecycleRepository.refresh` always repoints an environment
at the dataset's current latest ACTIVE `DatasetVersion` -- which was
produced by a full, fresh run of the Phase 6 certification pipeline
(INGEST -> ... -> CERTIFY), not by reprocessing only what changed since
the previous version. That is a real, honest limitation: this platform
does not implement change-data-capture or incremental reprocessing
anywhere.

`ROADMAP.md` Phase 8 nonetheless asks for a mechanism *demonstrating*
incremental refresh. The honest way to do that without fabricating an
engine that does not exist: compute a real row-count delta between two
already-registered `DatasetVersion`s of the same dataset (real
arithmetic on real, already-measured data), and report what a genuine
incremental-refresh engine would plausibly have reprocessed, as a
clearly-labeled *model* of an unbuilt capability -- never presented as
"this platform does incremental refresh." See
`docs/CAPACITY_COST_TRADEOFFS.md` for the full, honest framing and
`problems_phase_08.md` for this tracked explicitly as a modeled
illustration, not a shipped feature.
"""

from __future__ import annotations

from healthcare_tdm_contracts import DatasetVersion, IncrementalRefreshEstimate


def estimate_incremental_savings(
    previous: DatasetVersion, current: DatasetVersion
) -> IncrementalRefreshEstimate:
    """Compare two already-registered `DatasetVersion`s of the *same*
    `dataset_name` and model what an incremental refresh would have
    reprocessed, versus Phase 7's actual full-reprocessing `refresh()`.

    The model: for each entity, the number of rows unlikely to have
    needed reprocessing is `min(previous_count, current_count)` -- a
    conservative floor (it does not assume *which* rows are unchanged,
    only that at most that many could be, since a real CDC-aware engine
    could never claim more unchanged rows than the smaller of the two
    snapshots contains). Everything above that floor is modeled as
    "new/changed" and therefore part of the incremental workload.

    Raises `ValueError` if the two versions are not for the same
    `dataset_name`, or if `current.version_number <= previous.version_number`
    (comparing versions out of order would silently invert "previous" and
    "current").
    """

    if previous.dataset_name != current.dataset_name:
        raise ValueError(
            f"Cannot compare versions of different datasets: "
            f"{previous.dataset_name!r} vs {current.dataset_name!r}."
        )
    if current.version_number <= previous.version_number:
        raise ValueError(
            f"current.version_number ({current.version_number}) must be greater than "
            f"previous.version_number ({previous.version_number})."
        )

    entities = sorted(set(previous.row_counts) | set(current.row_counts))
    delta_by_entity: dict[str, int] = {}
    unchanged_estimate = 0
    for entity in entities:
        prev_count = previous.row_counts.get(entity, 0)
        curr_count = current.row_counts.get(entity, 0)
        delta_by_entity[entity] = curr_count - prev_count
        unchanged_estimate += min(prev_count, curr_count)

    previous_total = sum(previous.row_counts.values())
    current_total = sum(current.row_counts.values())
    full_reprocess = current_total
    incremental_estimate = max(full_reprocess - unchanged_estimate, 0)
    savings_pct = (
        1.0 - (incremental_estimate / full_reprocess) if full_reprocess > 0 else 0.0
    )

    return IncrementalRefreshEstimate(
        dataset_name=current.dataset_name,
        previous_version_id=previous.version_id,
        previous_version_number=previous.version_number,
        current_version_id=current.version_id,
        current_version_number=current.version_number,
        previous_total_row_count=previous_total,
        current_total_row_count=current_total,
        row_count_delta_by_entity=delta_by_entity,
        unchanged_row_estimate=unchanged_estimate,
        full_reprocess_row_count=full_reprocess,
        estimated_incremental_row_count=incremental_estimate,
        estimated_savings_pct=savings_pct,
    )


__all__ = ["estimate_incremental_savings"]
