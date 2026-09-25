"""Dataset lifecycle and refresh management (Phase 7) -- orchestration
and policy logic, per `control_plane.domain`'s module docstring: no
direct database driver/HTTP I/O here beyond a `sqlalchemy.orm.Session`
handed in by the caller, so the cadence math and state-machine rules stay
unit-testable without a running API process.

Module map
----------
- `cadence.py` -- `compute_next_refresh`, the pure function that turns a
  `RefreshPolicy` + a baseline timestamp into a `next_refresh_at`.
- `state_machine.py` -- the enforced `DatasetVersionStatus` transition
  table (mirrors `data_plane.certification.state_machine`'s pattern).
- `scheduler.py` -- `RefreshOrchestrator`, the orchestration abstraction
  this phase requires (Airflow/Databricks/cloud-scheduler-compatible
  seam) plus `LocalRefreshOrchestrator`, a real in-process implementation.
- `errors.py` -- domain-specific exceptions, mapped to HTTP status codes
  by `control_plane.api.v1.lifecycle`.
- `repository.py` -- `LifecycleRepository`, the one place that reads/
  writes the Phase 7 tables (`control_plane.db.models`) and returns
  typed `healthcare_tdm_contracts` shapes to callers.
"""

from control_plane.domain.lifecycle.errors import (
    CannotSelectRevokedVersionError,
    DatasetVersionNotFoundError,
    EnvironmentRequestNotFoundError,
    InvalidDatasetVersionTransitionError,
    NoActiveDatasetVersionError,
    OnDemandRefreshNotAllowedError,
)
from control_plane.domain.lifecycle.repository import LifecycleRepository
from control_plane.domain.lifecycle.scheduler import LocalRefreshOrchestrator, RefreshOrchestrator

__all__ = [
    "CannotSelectRevokedVersionError",
    "DatasetVersionNotFoundError",
    "EnvironmentRequestNotFoundError",
    "InvalidDatasetVersionTransitionError",
    "LifecycleRepository",
    "LocalRefreshOrchestrator",
    "NoActiveDatasetVersionError",
    "OnDemandRefreshNotAllowedError",
    "RefreshOrchestrator",
]
