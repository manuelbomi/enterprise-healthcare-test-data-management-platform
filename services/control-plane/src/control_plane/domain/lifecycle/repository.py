"""`LifecycleRepository` -- the one place that reads and writes the
Phase 7 dataset lifecycle tables (`control_plane.db.models`).

Owns the business logic `ROADMAP.md` Phase 7 asks for: registering an
immutable dataset version from a Phase 6 `CertificationReport`,
requesting a dataset into an environment (without duplicating physical
storage -- see `register_dataset_version`'s and `request_environment`'s
docstrings), resolving/updating refresh policies, running an on-demand
or scheduled refresh, applying retention/expiry, and rolling back or
revoking a version.

Every public method takes a `sqlalchemy.orm.Session` it does not own
(handed in by the caller -- `control_plane.api.v1.lifecycle`'s FastAPI
dependency, or a test) and returns typed `healthcare_tdm_contracts`
Pydantic shapes, never a raw ORM row -- callers (the API layer, tests)
never need to import `control_plane.db.models` directly.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from uuid import UUID, uuid4

from healthcare_tdm_contracts import (
    DEFAULT_CADENCE_BY_ENVIRONMENT,
    CertificationReport,
    CertificationStatus,
    DatasetVersion,
    DatasetVersionStatus,
    Environment,
    EnvironmentDatasetRequest,
    EnvironmentRequestStatus,
    RefreshCadenceType,
    RefreshPolicy,
    RefreshRunRecord,
    RefreshTrigger,
    RollbackRecord,
)
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from control_plane.db.models import (
    DatasetVersionRow,
    EnvironmentDatasetRequestRow,
    RefreshPolicyRow,
    RefreshRunRow,
    RollbackEventRow,
)
from control_plane.domain.lifecycle import cadence
from control_plane.domain.lifecycle import state_machine as version_state_machine
from control_plane.domain.lifecycle.errors import (
    CannotSelectRevokedVersionError,
    DatasetVersionNotFoundError,
    EnvironmentRequestNotFoundError,
    NoActiveDatasetVersionError,
    OnDemandRefreshNotAllowedError,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _new_id() -> str:
    return str(uuid4())


class LifecycleRepository:
    """Business logic + persistence for the dataset lifecycle domain.
    One instance per request/unit-of-work (cheap to construct -- holds
    only the session reference)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @property
    def session(self) -> Session:
        """The `Session` this repository was constructed with. Exposed
        (Phase 11) so cross-cutting platform helpers that must share
        the exact same transaction --
        `control_plane.platform.dead_letter.DeadLetterStore`,
        `control_plane.platform.audit.AuditLogRepository` -- can be
        constructed from it without reaching into a private attribute,
        the same reasoning `GovernanceRepository` already composes a
        `LifecycleRepository` sharing one `Session` (see ADR-0014)."""

        return self._session

    # ------------------------------------------------------------------
    # Dataset versions
    # ------------------------------------------------------------------

    def register_dataset_version(
        self,
        *,
        dataset_name: str,
        certification_report: CertificationReport,
        storage_uri: str,
        size_bytes: int,
        row_counts: dict[str, int],
        created_by: str,
        retention_days: int = 90,
        notes: str = "",
    ) -> DatasetVersion:
        """Register a new immutable dataset version from a Phase 6
        `CertificationReport`.

        Only a `CERTIFIED` or `PUBLISHED` report may be registered --
        `ARCHITECTURE.md`'s "a published certified dataset is exactly
        what this phase manages the lifecycle of" is enforced here, not
        just documented: a `DRAFT`/`PROCESSING`/`FAILED`/`REVOKED`
        report raises `ValueError`.

        `version_number` is assigned as `1 + max(existing version_number
        for this dataset_name)` -- monotonically increasing per dataset,
        never reused even after a version is revoked/expired.

        This is the *only* place a `DatasetVersionRow` (and therefore a
        physical `storage_uri`) is created. `request_environment` below
        never creates a new one -- every environment that requests this
        dataset while this version is the latest ACTIVE one points its
        `current_version_id` at *this* row. That reference, not a copy,
        is the "avoid unnecessary duplicate physical copies" mechanism
        this phase requires; see `docs/adr/0012-refresh-orchestration-abstraction.md`.

        **Idempotent per `certification_report_id`** (Phase 11): if a
        `DatasetVersionRow` already exists for this exact
        `certification_report.report_id`, that existing row is returned
        unchanged rather than creating a second one. This closes a real
        gap found while writing this phase's job-idempotency
        failure-injection test -- a caller that retries this call after
        an ambiguous failure (e.g. a network timeout where the first
        call actually succeeded server-side) used to create two
        distinct, differently-numbered versions pointing at the same
        `storage_uri`, mirroring the exact idempotency convention
        `request_environment` already documents for itself below. See
        `problems_phase_11.md`'s "Resolved problems" section.
        """

        if certification_report.status not in (
            CertificationStatus.CERTIFIED,
            CertificationStatus.PUBLISHED,
        ):
            raise ValueError(
                "Can only register a dataset version from a CERTIFIED or PUBLISHED "
                f"CertificationReport; got status={certification_report.status.value!r} "
                f"for report {certification_report.report_id}."
            )

        existing = self._session.scalars(
            select(DatasetVersionRow).where(
                DatasetVersionRow.certification_report_id == str(certification_report.report_id)
            )
        ).first()
        if existing is not None:
            return self._version_to_contract(existing)

        max_version = self._session.scalar(
            select(func.max(DatasetVersionRow.version_number)).where(
                DatasetVersionRow.dataset_name == dataset_name
            )
        )
        version_number = (max_version or 0) + 1
        created_at = _now()

        row = DatasetVersionRow(
            version_id=_new_id(),
            dataset_name=dataset_name,
            version_number=version_number,
            certification_report_id=str(certification_report.report_id),
            masking_policy_name=certification_report.masking_policy_name,
            masking_policy_version=certification_report.masking_policy_version,
            masking_engine_version=certification_report.masking_engine_version,
            storage_uri=storage_uri,
            size_bytes=size_bytes,
            row_counts_json=json.dumps(row_counts),
            status=DatasetVersionStatus.ACTIVE.value,
            created_at=created_at,
            created_by=created_by,
            retention_days=retention_days,
            expires_at=created_at + timedelta(days=retention_days),
            notes=notes,
        )
        self._session.add(row)
        self._session.flush()
        return self._version_to_contract(row)

    def get_version(self, version_id: UUID | str) -> DatasetVersion:
        row = self._get_version_row(version_id)
        return self._version_to_contract(row)

    def list_versions(
        self, *, dataset_name: str | None = None, status: DatasetVersionStatus | None = None
    ) -> list[DatasetVersion]:
        stmt = select(DatasetVersionRow)
        if dataset_name is not None:
            stmt = stmt.where(DatasetVersionRow.dataset_name == dataset_name)
        if status is not None:
            stmt = stmt.where(DatasetVersionRow.status == status.value)
        stmt = stmt.order_by(DatasetVersionRow.dataset_name, DatasetVersionRow.version_number)
        rows = self._session.scalars(stmt).all()
        return [self._version_to_contract(row) for row in rows]

    def get_latest_active_version(self, dataset_name: str) -> DatasetVersionRow | None:
        stmt = (
            select(DatasetVersionRow)
            .where(
                DatasetVersionRow.dataset_name == dataset_name,
                DatasetVersionRow.status == DatasetVersionStatus.ACTIVE.value,
            )
            .order_by(DatasetVersionRow.version_number.desc())
            .limit(1)
        )
        return self._session.scalars(stmt).first()

    def revoke_version(
        self, version_id: UUID | str, *, reason: str, revoked_by: str
    ) -> DatasetVersion:
        """Explicitly invalidate a version. Terminal: enforced by
        `version_state_machine.transition` (ACTIVE/EXPIRED/ROLLED_BACK ->
        REVOKED only). Does **not** move any environment currently
        pointed at this version onto another one automatically -- see
        `DatasetVersionStatus.REVOKED`'s docstring for why that is a
        deliberate choice, not an oversight. `request_environment`,
        `refresh`, and `rollback` below all refuse to newly *select* a
        revoked version going forward.
        """

        if not reason.strip():
            raise ValueError("A revocation reason is required.")

        row = self._get_version_row(version_id)
        current = DatasetVersionStatus(row.status)
        version_state_machine.transition(current, DatasetVersionStatus.REVOKED)

        row.status = DatasetVersionStatus.REVOKED.value
        row.revoked_at = _now()
        row.revoked_reason = reason
        row.revoked_by = revoked_by
        self._session.flush()
        return self._version_to_contract(row)

    def apply_retention(self, *, as_of: datetime | None = None) -> list[DatasetVersion]:
        """Expire every ACTIVE version whose `expires_at <= as_of`
        (default: now). Returns the versions that were just expired.
        Intended to be run periodically by the same scheduler that would
        drive `RefreshOrchestrator.run_due_refreshes` (see ADR-0012) --
        exposed here as a plain repository method so it can be called
        directly by a test, a script, or a future scheduled task without
        needing a live API process.
        """

        as_of = as_of or _now()
        stmt = select(DatasetVersionRow).where(
            DatasetVersionRow.status == DatasetVersionStatus.ACTIVE.value,
            DatasetVersionRow.expires_at.is_not(None),
            DatasetVersionRow.expires_at <= as_of,
        )
        expired: list[DatasetVersion] = []
        for row in self._session.scalars(stmt).all():
            version_state_machine.transition(DatasetVersionStatus.ACTIVE, DatasetVersionStatus.EXPIRED)
            row.status = DatasetVersionStatus.EXPIRED.value
            expired.append(self._version_to_contract(row))
        self._session.flush()
        return expired

    # ------------------------------------------------------------------
    # Refresh policies
    # ------------------------------------------------------------------

    def get_or_create_default_policy(self, environment: Environment) -> RefreshPolicy:
        """The environment-wide default policy (`dataset_name=None`),
        seeded from `DEFAULT_CADENCE_BY_ENVIRONMENT` the first time it is
        asked for. These defaults are `ROADMAP.md` Phase 7's
        demonstration cadences (DEV/QA weekly, SIT biweekly, UAT
        release-driven, PERFORMANCE monthly) -- a starting point, not a
        hardcoded rule; `upsert_policy` can change any of it afterward.
        """

        row = self._session.scalars(
            select(RefreshPolicyRow).where(
                RefreshPolicyRow.environment == environment.value,
                RefreshPolicyRow.dataset_name.is_(None),
            )
        ).first()
        if row is not None:
            return self._policy_to_contract(row)

        cadence_type = DEFAULT_CADENCE_BY_ENVIRONMENT[environment]
        now = _now()
        row = RefreshPolicyRow(
            policy_id=_new_id(),
            policy_version=1,
            environment=environment.value,
            dataset_name=None,
            cadence_type=cadence_type.value,
            interval_days=None,
            retention_days=90,
            grace_period_days=3,
            on_demand_allowed=True,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        self._session.add(row)
        self._session.flush()
        return self._policy_to_contract(row)

    def upsert_policy(
        self,
        *,
        environment: Environment,
        dataset_name: str | None,
        cadence_type: RefreshCadenceType,
        interval_days: int | None,
        retention_days: int,
        grace_period_days: int,
        on_demand_allowed: bool,
    ) -> RefreshPolicy:
        """Create or update the policy for `(environment, dataset_name)`.
        Updating an existing policy bumps `policy_version` -- every
        `EnvironmentDatasetRequest` records which `policy_version` it was
        last scheduled under (`request_environment`/`refresh`), so a
        later audit can tell exactly which cadence rule was in force at
        the time."""

        row = self._session.scalars(
            select(RefreshPolicyRow).where(
                RefreshPolicyRow.environment == environment.value,
                RefreshPolicyRow.dataset_name == dataset_name,
            )
        ).first()
        now = _now()
        if row is None:
            row = RefreshPolicyRow(
                policy_id=_new_id(),
                policy_version=1,
                environment=environment.value,
                dataset_name=dataset_name,
                created_at=now,
            )
            self._session.add(row)
        else:
            row.policy_version += 1

        row.cadence_type = cadence_type.value
        row.interval_days = interval_days
        row.retention_days = retention_days
        row.grace_period_days = grace_period_days
        row.on_demand_allowed = on_demand_allowed
        row.is_active = True
        row.updated_at = now
        self._session.flush()
        return self._policy_to_contract(row)

    def list_policies(
        self, *, environment: Environment | None = None
    ) -> list[RefreshPolicy]:
        stmt = select(RefreshPolicyRow)
        if environment is not None:
            stmt = stmt.where(RefreshPolicyRow.environment == environment.value)
        stmt = stmt.order_by(RefreshPolicyRow.environment, RefreshPolicyRow.dataset_name)
        rows = self._session.scalars(stmt).all()
        return [self._policy_to_contract(row) for row in rows]

    def resolve_policy(self, environment: Environment, dataset_name: str) -> RefreshPolicy:
        """The dataset-specific policy for `(environment, dataset_name)`
        if one has been configured, otherwise the environment-wide
        default (seeded on first use)."""

        row = self._session.scalars(
            select(RefreshPolicyRow).where(
                RefreshPolicyRow.environment == environment.value,
                RefreshPolicyRow.dataset_name == dataset_name,
            )
        ).first()
        if row is not None:
            return self._policy_to_contract(row)
        return self.get_or_create_default_policy(environment)

    # ------------------------------------------------------------------
    # Environment dataset requests
    # ------------------------------------------------------------------

    def request_environment(
        self,
        *,
        environment: Environment,
        dataset_name: str,
        requested_by: str,
        consumer: str = "",
    ) -> EnvironmentDatasetRequest:
        """Request a dataset into an environment.

        Idempotent per `(environment, dataset_name)`: if a request
        already exists, it is returned unchanged (this call never
        creates a second row, and never creates a second physical copy
        of anything -- it points at the same `DatasetVersionRow` every
        other environment requesting this dataset also points at).
        Raises `NoActiveDatasetVersionError` if no ACTIVE version of
        `dataset_name` has been registered yet.
        """

        existing = self._session.scalars(
            select(EnvironmentDatasetRequestRow).where(
                EnvironmentDatasetRequestRow.environment == environment.value,
                EnvironmentDatasetRequestRow.dataset_name == dataset_name,
            )
        ).first()
        if existing is not None:
            return self._request_to_contract(existing)

        latest = self.get_latest_active_version(dataset_name)
        if latest is None:
            raise NoActiveDatasetVersionError(
                f"No ACTIVE dataset version registered for dataset_name={dataset_name!r}. "
                "Register one via register_dataset_version first."
            )

        policy = self.resolve_policy(environment, dataset_name)
        now = _now()
        next_refresh = cadence.compute_next_refresh(
            policy.cadence_type, interval_days=policy.interval_days, baseline=now
        )

        row = EnvironmentDatasetRequestRow(
            request_id=_new_id(),
            environment=environment.value,
            dataset_name=dataset_name,
            current_version_id=latest.version_id,
            status=EnvironmentRequestStatus.ACTIVE.value,
            policy_id=str(policy.policy_id),
            policy_version=policy.policy_version,
            consumer=consumer,
            requested_by=requested_by,
            requested_at=now,
            last_refresh_at=None,
            next_refresh_at=next_refresh,
        )
        self._session.add(row)
        self._session.flush()
        return self._request_to_contract(row)

    def get_request(self, request_id: UUID | str) -> EnvironmentDatasetRequest:
        row = self._get_request_row(request_id)
        return self._request_to_contract(row)

    def list_requests(
        self, *, environment: Environment | None = None, dataset_name: str | None = None
    ) -> list[EnvironmentDatasetRequest]:
        stmt = select(EnvironmentDatasetRequestRow)
        if environment is not None:
            stmt = stmt.where(EnvironmentDatasetRequestRow.environment == environment.value)
        if dataset_name is not None:
            stmt = stmt.where(EnvironmentDatasetRequestRow.dataset_name == dataset_name)
        stmt = stmt.order_by(
            EnvironmentDatasetRequestRow.dataset_name, EnvironmentDatasetRequestRow.environment
        )
        rows = self._session.scalars(stmt).all()
        return [self._request_to_contract(row) for row in rows]

    def list_due_refreshes(self, as_of: datetime) -> list[EnvironmentDatasetRequest]:
        """Every ACTIVE request whose `next_refresh_at` is set and
        `<= as_of` -- the query `RefreshOrchestrator.due_refreshes`
        delegates to."""

        stmt = select(EnvironmentDatasetRequestRow).where(
            EnvironmentDatasetRequestRow.status == EnvironmentRequestStatus.ACTIVE.value,
            EnvironmentDatasetRequestRow.next_refresh_at.is_not(None),
            EnvironmentDatasetRequestRow.next_refresh_at <= as_of,
        )
        rows = self._session.scalars(stmt).all()
        return [self._request_to_contract(row) for row in rows]

    def refresh(
        self, request_id: UUID | str, *, trigger: RefreshTrigger, triggered_by: str
    ) -> RefreshRunRecord:
        """Execute one refresh: point the request at the dataset's
        current latest ACTIVE version (a no-op version-wise if it was
        already on it -- refreshing still recomputes `next_refresh_at`
        from now), and recompute the schedule.

        On-demand refreshes are rejected with
        `OnDemandRefreshNotAllowedError` if the applicable policy's
        `on_demand_allowed` is `False`. A `RELEASE_DRIVEN`/`ON_DEMAND`
        cadence has no automatic schedule at all
        (`next_refresh_at` stays `None`) -- those requests are only ever
        refreshed this way, exactly matching UAT's release-driven and
        PERFORMANCE's monthly/on-demand cadences from `ROADMAP.md`.
        """

        row = self._get_request_row(request_id)
        policy = self.resolve_policy(Environment(row.environment), row.dataset_name)

        if trigger is RefreshTrigger.ON_DEMAND and not policy.on_demand_allowed:
            raise OnDemandRefreshNotAllowedError(
                f"On-demand refresh is not allowed by policy for environment="
                f"{row.environment!r} dataset_name={row.dataset_name!r}."
            )

        run_id = _new_id()
        started_at = _now()
        previous_version_id = row.current_version_id

        latest = self.get_latest_active_version(row.dataset_name)
        if latest is None:
            run_row = RefreshRunRow(
                run_id=run_id,
                request_id=row.request_id,
                environment=row.environment,
                dataset_name=row.dataset_name,
                trigger=trigger.value,
                triggered_by=triggered_by,
                started_at=started_at,
                finished_at=_now(),
                previous_version_id=previous_version_id,
                resulting_version_id=None,
                succeeded=False,
                detail="No ACTIVE dataset version available to refresh to.",
            )
            self._session.add(run_row)
            self._session.flush()
            return self._run_to_contract(run_row)

        row.current_version_id = latest.version_id
        row.policy_id = str(policy.policy_id)
        row.policy_version = policy.policy_version
        row.last_refresh_at = started_at
        row.next_refresh_at = cadence.compute_next_refresh(
            policy.cadence_type, interval_days=policy.interval_days, baseline=started_at
        )

        run_row = RefreshRunRow(
            run_id=run_id,
            request_id=row.request_id,
            environment=row.environment,
            dataset_name=row.dataset_name,
            trigger=trigger.value,
            triggered_by=triggered_by,
            started_at=started_at,
            finished_at=_now(),
            previous_version_id=previous_version_id,
            resulting_version_id=latest.version_id,
            succeeded=True,
            detail=(
                f"Refreshed to version {latest.version_number}"
                if previous_version_id != latest.version_id
                else f"Already on latest ACTIVE version {latest.version_number}; schedule recomputed."
            ),
        )
        self._session.add(run_row)
        self._session.flush()
        return self._run_to_contract(run_row)

    def rollback(
        self,
        request_id: UUID | str,
        *,
        to_version_number: int,
        performed_by: str,
        reason: str,
    ) -> RollbackRecord:
        """Roll one environment's request back to an earlier version of
        the same dataset.

        Refuses to roll back to a `REVOKED` version
        (`CannotSelectRevokedVersionError`). After moving the pointer:
        - if the version being rolled back *from* is no longer
          referenced by any environment request, it transitions
          ACTIVE -> ROLLED_BACK (see `DatasetVersionStatus.ROLLED_BACK`);
        - if the version being rolled back *to* was ROLLED_BACK, it
          transitions back to ACTIVE (an environment is using it again).
        Neither transition fires if the version is shared with another
        environment still actively using it -- rollback is scoped to one
        environment's pointer, never a whole dataset version's global
        status, unless this rollback happens to be the action that makes
        it unreferenced/referenced again.
        """

        if not reason.strip():
            raise ValueError("A rollback reason is required.")

        request_row = self._get_request_row(request_id)
        dataset_name = request_row.dataset_name

        target_row = self._session.scalars(
            select(DatasetVersionRow).where(
                DatasetVersionRow.dataset_name == dataset_name,
                DatasetVersionRow.version_number == to_version_number,
            )
        ).first()
        if target_row is None:
            raise DatasetVersionNotFoundError(
                f"No version_number={to_version_number} registered for dataset_name={dataset_name!r}."
            )
        if DatasetVersionStatus(target_row.status) is DatasetVersionStatus.REVOKED:
            raise CannotSelectRevokedVersionError(
                f"Cannot roll back to version {to_version_number} of {dataset_name!r}: it is REVOKED."
            )

        from_version_id = request_row.current_version_id
        from_row = self._session.get(DatasetVersionRow, from_version_id)

        request_row.current_version_id = target_row.version_id
        self._session.flush()

        # If the FROM version is no longer referenced by any environment
        # request, mark it ROLLED_BACK (only if it is still ACTIVE --
        # never override an EXPIRED/REVOKED status).
        if from_row is not None and from_row.version_id != target_row.version_id:
            still_referenced = self._session.scalar(
                select(func.count()).select_from(EnvironmentDatasetRequestRow).where(
                    EnvironmentDatasetRequestRow.current_version_id == from_row.version_id
                )
            )
            if not still_referenced and DatasetVersionStatus(from_row.status) is DatasetVersionStatus.ACTIVE:
                version_state_machine.transition(
                    DatasetVersionStatus.ACTIVE, DatasetVersionStatus.ROLLED_BACK
                )
                from_row.status = DatasetVersionStatus.ROLLED_BACK.value
                from_row.rolled_back_at = _now()

        # If the TO version was ROLLED_BACK, it is being used again.
        if DatasetVersionStatus(target_row.status) is DatasetVersionStatus.ROLLED_BACK:
            version_state_machine.transition(
                DatasetVersionStatus.ROLLED_BACK, DatasetVersionStatus.ACTIVE
            )
            target_row.status = DatasetVersionStatus.ACTIVE.value

        event = RollbackEventRow(
            rollback_id=_new_id(),
            request_id=request_row.request_id,
            environment=request_row.environment,
            dataset_name=dataset_name,
            from_version_id=from_version_id,
            to_version_id=target_row.version_id,
            performed_by=performed_by,
            performed_at=_now(),
            reason=reason,
        )
        self._session.add(event)
        self._session.flush()

        from_version_number = from_row.version_number if from_row is not None else 0
        return RollbackRecord(
            rollback_id=UUID(event.rollback_id),
            request_id=UUID(request_row.request_id),
            environment=Environment(request_row.environment),
            dataset_name=dataset_name,
            from_version_id=UUID(from_version_id),
            from_version_number=from_version_number,
            to_version_id=UUID(target_row.version_id),
            to_version_number=target_row.version_number,
            performed_by=performed_by,
            performed_at=event.performed_at,
            reason=reason,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _get_version_row(self, version_id: UUID | str) -> DatasetVersionRow:
        row = self._session.get(DatasetVersionRow, str(version_id))
        if row is None:
            raise DatasetVersionNotFoundError(f"No dataset version with version_id={version_id!r}.")
        return row

    def _get_request_row(self, request_id: UUID | str) -> EnvironmentDatasetRequestRow:
        row = self._session.get(EnvironmentDatasetRequestRow, str(request_id))
        if row is None:
            raise EnvironmentRequestNotFoundError(
                f"No environment dataset request with request_id={request_id!r}."
            )
        return row

    def _referenced_by_environments(self, version_id: str) -> list[Environment]:
        stmt = select(EnvironmentDatasetRequestRow.environment).where(
            EnvironmentDatasetRequestRow.current_version_id == version_id
        )
        return [Environment(v) for v in self._session.scalars(stmt).all()]

    def _version_to_contract(self, row: DatasetVersionRow) -> DatasetVersion:
        return DatasetVersion(
            version_id=UUID(row.version_id),
            dataset_name=row.dataset_name,
            version_number=row.version_number,
            certification_report_id=UUID(row.certification_report_id),
            masking_policy_name=row.masking_policy_name,
            masking_policy_version=row.masking_policy_version,
            masking_engine_version=row.masking_engine_version,
            storage_uri=row.storage_uri,
            size_bytes=row.size_bytes,
            row_counts=json.loads(row.row_counts_json or "{}"),
            status=DatasetVersionStatus(row.status),
            created_at=row.created_at,
            created_by=row.created_by,
            retention_days=row.retention_days,
            expires_at=row.expires_at,
            revoked_at=row.revoked_at,
            revoked_reason=row.revoked_reason,
            revoked_by=row.revoked_by,
            rolled_back_at=row.rolled_back_at,
            notes=row.notes,
            referenced_by_environments=self._referenced_by_environments(row.version_id),
        )

    def _policy_to_contract(self, row: RefreshPolicyRow) -> RefreshPolicy:
        return RefreshPolicy(
            policy_id=UUID(row.policy_id),
            policy_version=row.policy_version,
            environment=Environment(row.environment),
            dataset_name=row.dataset_name,
            cadence_type=RefreshCadenceType(row.cadence_type),
            interval_days=row.interval_days,
            retention_days=row.retention_days,
            grace_period_days=row.grace_period_days,
            on_demand_allowed=row.on_demand_allowed,
            is_active=row.is_active,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    def _request_to_contract(self, row: EnvironmentDatasetRequestRow) -> EnvironmentDatasetRequest:
        version_row = self._session.get(DatasetVersionRow, row.current_version_id)
        version_number = version_row.version_number if version_row is not None else 0
        return EnvironmentDatasetRequest(
            request_id=UUID(row.request_id),
            environment=Environment(row.environment),
            dataset_name=row.dataset_name,
            current_version_id=UUID(row.current_version_id),
            current_version_number=version_number,
            status=EnvironmentRequestStatus(row.status),
            policy_id=UUID(row.policy_id),
            policy_version=row.policy_version,
            consumer=row.consumer,
            requested_by=row.requested_by,
            requested_at=row.requested_at,
            last_refresh_at=row.last_refresh_at,
            next_refresh_at=row.next_refresh_at,
        )

    def _run_to_contract(self, row: RefreshRunRow) -> RefreshRunRecord:
        return RefreshRunRecord(
            run_id=UUID(row.run_id),
            request_id=UUID(row.request_id),
            environment=Environment(row.environment),
            dataset_name=row.dataset_name,
            trigger=RefreshTrigger(row.trigger),
            triggered_by=row.triggered_by,
            started_at=row.started_at,
            finished_at=row.finished_at,
            previous_version_id=UUID(row.previous_version_id) if row.previous_version_id else None,
            resulting_version_id=UUID(row.resulting_version_id) if row.resulting_version_id else None,
            succeeded=row.succeeded,
            detail=row.detail,
        )


__all__ = ["LifecycleRepository"]
