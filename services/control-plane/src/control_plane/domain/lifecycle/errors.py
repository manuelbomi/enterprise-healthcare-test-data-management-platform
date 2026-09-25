"""Domain-specific exceptions for `control_plane.domain.lifecycle`.

Raised by `LifecycleRepository`; caught and translated to HTTP status
codes by `control_plane.api.v1.lifecycle` (never leaked as bare 500s for
conditions that are expected/recoverable, the same convention
`control_plane.catalog.CatalogNotAvailableError` already established for
the Phase 2 catalog API).
"""

from __future__ import annotations


class DatasetVersionNotFoundError(LookupError):
    """No `DatasetVersionRow` exists for the given identifier."""


class EnvironmentRequestNotFoundError(LookupError):
    """No `EnvironmentDatasetRequestRow` exists for the given identifier
    (or `(environment, dataset_name)` pair)."""


class NoActiveDatasetVersionError(RuntimeError):
    """A dataset has no ACTIVE version to request/refresh into -- either
    none has ever been registered, or every registered version has been
    expired/revoked/rolled back with nothing currently active."""


class InvalidDatasetVersionTransitionError(RuntimeError):
    """An attempted `DatasetVersionStatus` transition is not listed in
    `healthcare_tdm_contracts.DATASET_VERSION_STATUS_TRANSITIONS`."""


class OnDemandRefreshNotAllowedError(RuntimeError):
    """The applicable `RefreshPolicy.on_demand_allowed` is `False`, but
    an on-demand refresh was requested anyway."""


class CannotSelectRevokedVersionError(RuntimeError):
    """An operation (request, refresh, rollback-target) tried to point an
    environment at a `REVOKED` dataset version. Revocation is terminal
    and forward-looking: it blocks *new* selections but never silently
    moves an environment already on the version -- see
    `docs/tutorial/07-dataset-lifecycle-and-refresh.md`."""


__all__ = [
    "CannotSelectRevokedVersionError",
    "DatasetVersionNotFoundError",
    "EnvironmentRequestNotFoundError",
    "InvalidDatasetVersionTransitionError",
    "NoActiveDatasetVersionError",
    "OnDemandRefreshNotAllowedError",
]
