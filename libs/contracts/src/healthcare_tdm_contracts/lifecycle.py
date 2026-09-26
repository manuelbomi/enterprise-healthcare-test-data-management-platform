"""Dataset lifecycle and refresh management contracts (Phase 7).

`ROADMAP.md` Phase 7 treats a certified, published test dataset
(`CertificationReport`, Phase 6) as a *product*: once it exists, it has
versions, it is requested into environments, it is refreshed on a
cadence, it eventually expires or is explicitly revoked, and an
environment can be rolled back to a prior version. None of that is a
data-plane transformation -- it is durable, queryable *state* about
datasets that already exist, which is why it lives in the metadata plane
(`services/control-plane/src/control_plane/db`,
`services/control-plane/src/control_plane/domain/lifecycle`) rather than
as another JSON artifact next to a data-plane pipeline's output. See
`docs/adr/0012-refresh-orchestration-abstraction.md`.

Two closely related shapes already existed before this phase and are
deliberately *not* reused wholesale here:

- `certification.CertificationReport` is this phase's *input* -- a
  dataset version is only ever registered from a `CERTIFIED` or
  `PUBLISHED` report (see
  `control_plane.domain.lifecycle.repository.LifecycleRepository.register_dataset_version`).
  `certification.py`'s own module docstring already anticipates this:
  "a future Phase 7 snapshot registry integration would map
  `CertificationStatus.PUBLISHED` to `SnapshotStatus.PUBLISHED` ... not
  replace either vocabulary with the other."
- `snapshots.SnapshotRecord`/`SnapshotStatus` is a Phase 0 scaffold shape
  for a *single environment's* snapshot record (it has one
  `target_environment` field per record). This phase's core requirement
  -- "avoid unnecessary duplicate physical copies" when multiple
  environments request the same dataset -- is structurally incompatible
  with one record per (dataset, environment) pointing at its own
  storage location, so `DatasetVersion` here is deliberately
  environment-agnostic (one immutable artifact) and
  `EnvironmentDatasetRequest` is the separate, per-environment pointer
  that *references* a `DatasetVersion` rather than owning storage of its
  own. `SnapshotRecord` is left untouched (still exact Phase 0 scope,
  unused by this phase) rather than retrofitted -- see
  `docs/problems/problems_phase_07.md`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class Environment(str, Enum):
    """The lower environments this platform provisions certified test
    data into (`ROADMAP.md` Phase 7's example list)."""

    DEV = "dev"
    QA = "qa"
    SIT = "sit"
    UAT = "uat"
    PERFORMANCE = "performance"


class RefreshCadenceType(str, Enum):
    """How a `RefreshPolicy` decides when its next refresh is due.

    WEEKLY / BIWEEKLY / MONTHLY
        A fixed interval (in days, `RefreshPolicy.interval_days`) from
        the last refresh (or, for a brand-new request, from the request
        time).
    RELEASE_DRIVEN
        No automatic interval -- a human/CI system triggers a refresh
        tied to a release event, via the same on-demand refresh endpoint
        every other cadence also allows. `next_refresh_at` is left
        unset (``None``) for a release-driven policy; see
        `control_plane.domain.lifecycle.cadence`.
    ON_DEMAND
        No automatic schedule at all -- refreshed only when explicitly
        requested. Distinct from RELEASE_DRIVEN only in *why* there is
        no fixed interval (an environment that's expensive to refresh on
        a timer vs. one that's tied to an external release process).
    """

    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    RELEASE_DRIVEN = "release_driven"
    ON_DEMAND = "on_demand"


#: `ROADMAP.md` Phase 7's demonstration defaults, one per `Environment`:
#: DEV/QA weekly, SIT biweekly, UAT release-driven, PERFORMANCE monthly
#: (with on-demand always additionally allowed -- see
#: `RefreshPolicy.on_demand_allowed`, which defaults to `True` for every
#: cadence type including this one). These are only the seed values a
#: fresh control-plane database is bootstrapped with
#: (`LifecycleRepository.get_or_create_default_policy`) -- every field is
#: runtime-configurable afterward via
#: `PUT /api/v1/lifecycle/refresh-policies`, never hardcoded into engine
#: logic.
DEFAULT_CADENCE_BY_ENVIRONMENT: dict[Environment, RefreshCadenceType] = {
    Environment.DEV: RefreshCadenceType.WEEKLY,
    Environment.QA: RefreshCadenceType.WEEKLY,
    Environment.SIT: RefreshCadenceType.BIWEEKLY,
    Environment.UAT: RefreshCadenceType.RELEASE_DRIVEN,
    Environment.PERFORMANCE: RefreshCadenceType.MONTHLY,
}

#: Default interval, in days, for the fixed-interval cadence types.
#: `None` for cadence types with no fixed interval. Also overridable per
#: policy via `RefreshPolicy.interval_days`.
DEFAULT_INTERVAL_DAYS_BY_CADENCE: dict[RefreshCadenceType, int | None] = {
    RefreshCadenceType.WEEKLY: 7,
    RefreshCadenceType.BIWEEKLY: 14,
    RefreshCadenceType.MONTHLY: 30,
    RefreshCadenceType.RELEASE_DRIVEN: None,
    RefreshCadenceType.ON_DEMAND: None,
}


class DatasetVersionStatus(str, Enum):
    """Lifecycle of one immutable, registered dataset version.

    ACTIVE
        Available to be requested/refreshed into by any environment.
    EXPIRED
        Past its retention window (`DatasetVersion.expires_at`);
        reached automatically by
        `LifecycleRepository.apply_retention`, never by deletion of the
        row -- the same "expire the record, never delete it" pattern
        `ARCHITECTURE.md` section 3.4 already establishes for snapshots.
    REVOKED
        Explicitly invalidated (e.g. a defect discovered after
        publication). Terminal: a revoked version can never be selected
        for a new environment request or a new refresh going forward
        (see `control_plane.domain.lifecycle.repository`'s
        `NoActiveDatasetVersionError` / version-selection guards) --
        though an environment already pointed at it when it was revoked
        is *not* automatically moved off it (see
        `docs/tutorial/07-dataset-lifecycle-and-refresh.md` for the
        documented, deliberate reasoning: a silent forced migration is
        its own operational risk, so revocation is visible in the API
        response instead and the operator decides the next action,
        typically a rollback or an on-demand refresh).
    ROLLED_BACK
        No environment is currently using this version *because* the
        most recent transition away from it was an explicit rollback
        (as opposed to a normal forward refresh, which leaves the old
        version ACTIVE and simply unreferenced). Distinguishes "we
        deliberately backed away from this version" from "nobody
        happens to be on it right now" in the version listing an
        auditor reviews. A version can be rolled back into again
        (ROLLED_BACK -> ACTIVE), matching real operational reality
        (a rollback is not necessarily final).
    """

    ACTIVE = "active"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ROLLED_BACK = "rolled_back"


#: The allowed-transition table (data only -- enforcement lives in
#: `control_plane.domain.lifecycle.state_machine`, mirroring the split
#: `certification.py`/`data_plane.certification.state_machine` already
#: established in Phase 6).
DATASET_VERSION_STATUS_TRANSITIONS: dict[
    DatasetVersionStatus, frozenset[DatasetVersionStatus]
] = {
    DatasetVersionStatus.ACTIVE: frozenset(
        {
            DatasetVersionStatus.EXPIRED,
            DatasetVersionStatus.REVOKED,
            DatasetVersionStatus.ROLLED_BACK,
        }
    ),
    DatasetVersionStatus.ROLLED_BACK: frozenset(
        {DatasetVersionStatus.ACTIVE, DatasetVersionStatus.REVOKED}
    ),
    DatasetVersionStatus.EXPIRED: frozenset({DatasetVersionStatus.REVOKED}),
    DatasetVersionStatus.REVOKED: frozenset(),
}


class RefreshTrigger(str, Enum):
    """What caused one `RefreshRunRecord` -- a scheduled sweep (see
    `control_plane.domain.lifecycle.scheduler.RefreshOrchestrator`) or an
    explicit on-demand call."""

    SCHEDULED = "scheduled"
    ON_DEMAND = "on_demand"


class EnvironmentRequestStatus(str, Enum):
    """Lifecycle of one environment's standing request for a dataset."""

    ACTIVE = "active"
    PAUSED = "paused"
    RETIRED = "retired"


class RefreshPolicy(BaseModel):
    """A configured refresh policy, scoped to one environment and
    (optionally) one dataset.

    `dataset_name=None` is the environment-wide default policy (one per
    `Environment`, seeded from `DEFAULT_CADENCE_BY_ENVIRONMENT`); a
    dataset-specific override with the same `environment` and a real
    `dataset_name` takes precedence when both exist -- see
    `LifecycleRepository.resolve_policy`.
    """

    policy_id: UUID = Field(default_factory=uuid4)
    policy_version: int = Field(
        default=1, ge=1, description="Bumped every time this policy's cadence/retention is edited."
    )
    environment: Environment
    dataset_name: str | None = Field(
        default=None, description="None = environment-wide default policy."
    )
    cadence_type: RefreshCadenceType
    interval_days: int | None = Field(
        default=None,
        description="Refresh interval in days for WEEKLY/BIWEEKLY/MONTHLY cadences. "
        "Falls back to DEFAULT_INTERVAL_DAYS_BY_CADENCE when unset.",
    )
    retention_days: int = Field(
        default=90, ge=1, description="How long a dataset version registered under this policy's "
        "environment stays ACTIVE before automatic expiry."
    )
    grace_period_days: int = Field(
        default=3,
        ge=0,
        description="How many days past next_refresh_at a request may go before it is "
        "considered overdue by the scheduler (reporting only; does not block refresh).",
    )
    on_demand_allowed: bool = Field(default=True)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class DatasetVersion(BaseModel):
    """An immutable, registered dataset version -- the durable record of
    one certified/published dataset snapshot.

    Deliberately environment-agnostic: many `EnvironmentDatasetRequest`
    rows across many environments may reference the same
    `DatasetVersion` (same `storage_uri`) at once. That reference --
    not a physical copy -- is the mechanism this phase uses to satisfy
    "avoid unnecessary duplicate physical copies." See
    `docs/adr/0012-refresh-orchestration-abstraction.md` and
    `docs/tutorial/07-dataset-lifecycle-and-refresh.md`.
    """

    version_id: UUID = Field(default_factory=uuid4)
    dataset_name: str
    version_number: int = Field(
        ..., ge=1, description="Monotonically increasing per dataset_name, assigned at registration."
    )
    certification_report_id: UUID = Field(
        ..., description="The Phase 6 CertificationReport.report_id this version was registered from."
    )
    masking_policy_name: str
    masking_policy_version: int
    masking_engine_version: str
    storage_uri: str = Field(
        ..., description="Location of the immutable snapshot artifact (directory/object prefix); "
        "never duplicated per-environment."
    )
    size_bytes: int = Field(..., ge=0)
    row_counts: dict[str, int] = Field(default_factory=dict)
    status: DatasetVersionStatus = DatasetVersionStatus.ACTIVE
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str
    retention_days: int = Field(default=90, ge=1)
    expires_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None
    revoked_by: str | None = None
    rolled_back_at: datetime | None = None
    notes: str = Field(default="")
    referenced_by_environments: list[Environment] = Field(
        default_factory=list,
        description="Environments whose EnvironmentDatasetRequest.current_version_id currently "
        "points at this version -- computed at read time, not stored, so it is always accurate.",
    )


class EnvironmentDatasetRequest(BaseModel):
    """One environment's standing request for a dataset: a pointer to the
    `DatasetVersion` it currently uses, plus its own refresh-schedule
    state. Unique per (`environment`, `dataset_name`) -- requesting the
    same dataset into a second environment creates a second row that
    points at the *same* `DatasetVersion`, never a second physical copy.
    """

    request_id: UUID = Field(default_factory=uuid4)
    environment: Environment
    dataset_name: str
    current_version_id: UUID
    current_version_number: int
    status: EnvironmentRequestStatus = EnvironmentRequestStatus.ACTIVE
    policy_id: UUID
    policy_version: int
    consumer: str = Field(
        default="", description="Free-text consumer/team label, e.g. 'claims-qa-team'."
    )
    requested_by: str
    requested_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    last_refresh_at: datetime | None = None
    next_refresh_at: datetime | None = None


class RefreshRunRecord(BaseModel):
    """One execution of a refresh (scheduled or on-demand) against an
    `EnvironmentDatasetRequest`."""

    run_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    environment: Environment
    dataset_name: str
    trigger: RefreshTrigger
    triggered_by: str
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    finished_at: datetime | None = None
    previous_version_id: UUID | None = None
    resulting_version_id: UUID | None = None
    succeeded: bool | None = None
    detail: str = Field(default="")


class RollbackRecord(BaseModel):
    """Durable rollback metadata: one environment's dataset pointer moved
    from one `DatasetVersion` to an earlier one."""

    rollback_id: UUID = Field(default_factory=uuid4)
    request_id: UUID
    environment: Environment
    dataset_name: str
    from_version_id: UUID
    from_version_number: int
    to_version_id: UUID
    to_version_number: int
    performed_by: str
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    reason: str


__all__ = [
    "DATASET_VERSION_STATUS_TRANSITIONS",
    "DEFAULT_CADENCE_BY_ENVIRONMENT",
    "DEFAULT_INTERVAL_DAYS_BY_CADENCE",
    "DatasetVersion",
    "DatasetVersionStatus",
    "Environment",
    "EnvironmentDatasetRequest",
    "EnvironmentRequestStatus",
    "RefreshCadenceType",
    "RefreshPolicy",
    "RefreshRunRecord",
    "RefreshTrigger",
    "RollbackRecord",
]
