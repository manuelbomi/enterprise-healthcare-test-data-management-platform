"""The enforced `DatasetVersionStatus` transition rule.

Mirrors the split `data_plane.certification.state_machine` already
established in Phase 6: the transition *table* is data, living in
`healthcare_tdm_contracts.DATASET_VERSION_STATUS_TRANSITIONS`; this
module is the one place that *enforces* it -- every status change on a
`DatasetVersionRow` goes through `transition()`, which raises
`InvalidDatasetVersionTransitionError` for anything not listed in that
table, so an invalid transition is rejected by code, not merely
documented.
"""

from __future__ import annotations

from healthcare_tdm_contracts import DATASET_VERSION_STATUS_TRANSITIONS, DatasetVersionStatus

from control_plane.domain.lifecycle.errors import InvalidDatasetVersionTransitionError


def transition(current: DatasetVersionStatus, target: DatasetVersionStatus) -> DatasetVersionStatus:
    """Validate `current -> target` against
    `DATASET_VERSION_STATUS_TRANSITIONS` and return `target` on success.
    Raises `InvalidDatasetVersionTransitionError` otherwise. A no-op
    transition (`current == target`) is always rejected -- callers that
    want idempotent "ensure this status" behavior should check equality
    themselves before calling this function, the same convention
    `data_plane.certification.state_machine` established.
    """

    allowed = DATASET_VERSION_STATUS_TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise InvalidDatasetVersionTransitionError(
            f"Cannot transition dataset version status from {current.value!r} to "
            f"{target.value!r}. Allowed from {current.value!r}: "
            f"{sorted(s.value for s in allowed) or 'none (terminal)'}."
        )
    return target


__all__ = ["transition"]
