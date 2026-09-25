"""Refresh cadence math: turn a `RefreshPolicy` into a concrete
`next_refresh_at` timestamp.

Kept as a small set of pure functions (no I/O, no database session) so
the cadence rules for all five example environments -- DEV/QA weekly,
SIT biweekly, UAT release-driven, PERFORMANCE monthly/on-demand -- are
independently unit-testable and never hidden inside a bigger
repository method. See `healthcare_tdm_contracts.RefreshCadenceType`
and `DEFAULT_CADENCE_BY_ENVIRONMENT`/`DEFAULT_INTERVAL_DAYS_BY_CADENCE`
for the demonstration defaults this module resolves against when a
policy doesn't set an explicit `interval_days`.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from healthcare_tdm_contracts import DEFAULT_INTERVAL_DAYS_BY_CADENCE, RefreshCadenceType


def resolve_interval_days(cadence_type: RefreshCadenceType, interval_days: int | None) -> int | None:
    """An explicit `interval_days` on the policy always wins; otherwise
    fall back to `DEFAULT_INTERVAL_DAYS_BY_CADENCE`. Returns `None` for
    cadence types with no fixed interval (RELEASE_DRIVEN, ON_DEMAND)."""

    if interval_days is not None:
        return interval_days
    return DEFAULT_INTERVAL_DAYS_BY_CADENCE[cadence_type]


def compute_next_refresh(
    cadence_type: RefreshCadenceType,
    *,
    interval_days: int | None,
    baseline: datetime,
) -> datetime | None:
    """Compute the next scheduled refresh timestamp.

    `baseline` is the timestamp the interval is measured from -- the
    request's `last_refresh_at` if it has ever been refreshed, otherwise
    `requested_at` (its initial registration into the environment). For
    RELEASE_DRIVEN and ON_DEMAND cadences there is no fixed interval to
    compute from, so this returns `None`: those requests are only ever
    refreshed by an explicit on-demand call (see
    `LifecycleRepository.refresh`), and `RefreshOrchestrator.due_refreshes`
    correctly never selects a request whose `next_refresh_at` is `None`.
    """

    resolved = resolve_interval_days(cadence_type, interval_days)
    if resolved is None:
        return None
    return baseline + timedelta(days=resolved)


__all__ = ["compute_next_refresh", "resolve_interval_days"]
