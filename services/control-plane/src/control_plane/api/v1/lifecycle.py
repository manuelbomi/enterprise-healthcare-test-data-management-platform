"""Dataset lifecycle and refresh management endpoints (Phase 7).

Unlike `catalog.py` (Phase 2, a read-only view over a JSON artifact
another plane produces), this router is the control plane's first set
of endpoints backed by a real, writable database-backed domain model
(`control_plane.db`, `control_plane.domain.lifecycle`). See
`ARCHITECTURE.md` section 2.3 and `docs/adr/0012-refresh-orchestration-abstraction.md`.

Route handlers do exactly three things: resolve a `LifecycleRepository`
via dependency injection, call one of its methods, and translate domain
exceptions to HTTP status codes. No business logic lives here -- see
`control_plane.domain.lifecycle.repository` for that.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from healthcare_tdm_contracts import (
    AuditEventType,
    CertificationReport,
    DatasetVersion,
    DatasetVersionStatus,
    Environment,
    EnvironmentDatasetRequest,
    RefreshCadenceType,
    RefreshPolicy,
    RefreshRunRecord,
    RefreshTrigger,
    RollbackRecord,
)
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from control_plane.config import Settings, get_settings
from control_plane.db.session import build_session_factory, get_engine_for_url, session_scope
from control_plane.domain.lifecycle import (
    CannotSelectRevokedVersionError,
    DatasetVersionNotFoundError,
    EnvironmentRequestNotFoundError,
    InvalidDatasetVersionTransitionError,
    LifecycleRepository,
    LocalRefreshOrchestrator,
    NoActiveDatasetVersionError,
    OnDemandRefreshNotAllowedError,
)
from control_plane.platform.audit import AuditLogRepository
from control_plane.platform.rbac import AuthorizationError, Permission, Role, authorize

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])


# ----------------------------------------------------------------------
# Dependencies
# ----------------------------------------------------------------------


def get_db_session(settings: Settings = Depends(get_settings)) -> Iterator[Session]:
    """FastAPI dependency: one SQLAlchemy session per request, against
    the engine for `settings.lifecycle_database_url` (cached per URL so
    the schema is only created once per process -- see
    `control_plane.db.session.get_engine_for_url`).

    Tests override this dependency directly (see
    `services/control-plane/tests/test_lifecycle_api.py`) to point at a
    fresh temporary SQLite file per test, exactly the same pattern
    `api/v1/catalog.py`'s tests use for `get_catalog_repository`.
    """

    engine = get_engine_for_url(settings.lifecycle_database_url)
    factory = build_session_factory(engine)
    with session_scope(factory) as session:
        yield session


def get_lifecycle_repository(session: Session = Depends(get_db_session)) -> LifecycleRepository:
    return LifecycleRepository(session)


def get_audit_log(session: Session = Depends(get_db_session)) -> AuditLogRepository:
    """Phase 11: FastAPI caches a given `Depends()` callable's result
    per request, so this resolves to the *same* `Session` instance
    `get_lifecycle_repository` above uses within one request -- an
    audited mutation and its audit event (or a rejected mutation and
    its `ACCESS_DENIED` event) commit, or roll back, together. See
    `control_plane.platform.audit`'s module docstring."""

    return AuditLogRepository(session)


# ----------------------------------------------------------------------
# Request bodies
# ----------------------------------------------------------------------


class RegisterDatasetVersionRequest(BaseModel):
    """Register a new dataset version from a Phase 6 `CertificationReport`."""

    dataset_name: str
    certification_report: CertificationReport
    storage_uri: str
    size_bytes: int = Field(..., ge=0)
    row_counts: dict[str, int] = Field(default_factory=dict)
    created_by: str
    retention_days: int = Field(default=90, ge=1)
    notes: str = ""


class RevokeVersionRequest(BaseModel):
    reason: str
    revoked_by: str
    #: Phase 11: required, checked via `control_plane.platform.rbac.authorize`
    #: against `Permission.REVOKE_DATASET_VERSION` before the revocation
    #: is attempted. Not a no-op -- see `test_failure_injection.py`'s
    #: RBAC-rejection test.
    actor_role: Role


class UpsertPolicyRequest(BaseModel):
    environment: Environment
    dataset_name: str | None = None
    cadence_type: RefreshCadenceType
    interval_days: int | None = None
    retention_days: int = Field(default=90, ge=1)
    grace_period_days: int = Field(default=3, ge=0)
    on_demand_allowed: bool = True


class RequestDatasetRequest(BaseModel):
    environment: Environment
    dataset_name: str
    requested_by: str
    consumer: str = ""


class RefreshRequestBody(BaseModel):
    triggered_by: str
    trigger: RefreshTrigger = RefreshTrigger.ON_DEMAND


class RollbackRequestBody(BaseModel):
    to_version_number: int = Field(..., ge=1)
    performed_by: str
    reason: str
    #: Phase 11: required, checked against `Permission.ROLLBACK_DATASET_VERSION`.
    actor_role: Role


# ----------------------------------------------------------------------
# Dataset versions
# ----------------------------------------------------------------------


@router.post("/dataset-versions", response_model=DatasetVersion, status_code=201)
def register_dataset_version(
    body: RegisterDatasetVersionRequest,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> DatasetVersion:
    """Register a new immutable dataset version. Requires a `CERTIFIED`
    or `PUBLISHED` Phase 6 `CertificationReport` -- see
    `LifecycleRepository.register_dataset_version`, which is now
    idempotent per `certification_report_id` (Phase 11 -- see
    `problems_phase_11.md`'s "Resolved problems")."""

    try:
        version = repository.register_dataset_version(
            dataset_name=body.dataset_name,
            certification_report=body.certification_report,
            storage_uri=body.storage_uri,
            size_bytes=body.size_bytes,
            row_counts=body.row_counts,
            created_by=body.created_by,
            retention_days=body.retention_days,
            notes=body.notes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.DATASET_VERSION_REGISTERED,
        actor=body.created_by,
        # Subject is the version_id (not "dataset_name:vN") so every
        # audit event about the same dataset version -- registration,
        # a later revocation -- shares one `subject` an auditor can
        # query by (`GET /api/v1/audit/events?subject=<version_id>`).
        subject=str(version.version_id),
        outcome="allowed",
        detail={
            "dataset_name": body.dataset_name,
            "version_number": str(version.version_number),
            "storage_uri": body.storage_uri,
        },
    )
    return version


@router.get("/dataset-versions", response_model=list[DatasetVersion])
def list_dataset_versions(
    dataset_name: str | None = None,
    status: DatasetVersionStatus | None = None,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> list[DatasetVersion]:
    """List dataset versions with lifecycle status
    (active/expired/revoked/rolled_back), optionally filtered."""

    return repository.list_versions(dataset_name=dataset_name, status=status)


@router.get("/dataset-versions/{version_id}", response_model=DatasetVersion)
def get_dataset_version(
    version_id: UUID, repository: LifecycleRepository = Depends(get_lifecycle_repository)
) -> DatasetVersion:
    try:
        return repository.get_version(version_id)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/dataset-versions/{version_id}/revoke", response_model=DatasetVersion)
def revoke_dataset_version(
    version_id: UUID,
    body: RevokeVersionRequest,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> DatasetVersion:
    """Revoke a version. Environments already pointed at it are left
    alone (see `DatasetVersionStatus.REVOKED`'s docstring); a revoked
    version can never again be selected by `request_environment`,
    `refresh`, or `rollback`.

    Phase 11: requires `body.actor_role` to hold
    `Permission.REVOKE_DATASET_VERSION` (only `COMPLIANCE_APPROVER`/
    `PLATFORM_ADMIN` do -- see `control_plane.platform.rbac`). An
    unauthorized attempt is rejected with HTTP 403 *before* the
    repository is called at all, and is itself recorded as an
    `ACCESS_DENIED` audit event (committed immediately so the denial
    record survives the exception this handler then raises -- see
    `control_plane.platform.audit`'s module docstring for why this is
    the one handler in this router that calls `session.commit()`
    directly instead of relying on `session_scope`'s end-of-request
    commit)."""

    try:
        authorize(body.actor_role, Permission.REVOKE_DATASET_VERSION)
    except AuthorizationError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=body.revoked_by,
            subject=str(version_id),
            outcome="denied",
            detail={"permission": Permission.REVOKE_DATASET_VERSION.value, "actor_role": body.actor_role.value},
        )
        session.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        version = repository.revoke_version(version_id, reason=body.reason, revoked_by=body.revoked_by)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except InvalidDatasetVersionTransitionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit.record(
        event_type=AuditEventType.DATASET_VERSION_REVOKED,
        actor=body.revoked_by,
        subject=str(version_id),
        outcome="allowed",
        detail={"reason": body.reason, "actor_role": body.actor_role.value},
    )
    return version


# ----------------------------------------------------------------------
# Refresh policies
# ----------------------------------------------------------------------


@router.get("/refresh-policies", response_model=list[RefreshPolicy])
def list_refresh_policies(
    environment: Environment | None = None,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> list[RefreshPolicy]:
    """List configured refresh policies. Environment-wide defaults
    (`dataset_name=null`) are seeded on first access via
    `GET /refresh-policies/{environment}/default` or the first
    `POST /environment-requests` for that environment; this endpoint
    only lists policies that have actually been created."""

    return repository.list_policies(environment=environment)


@router.get("/refresh-policies/{environment}/default", response_model=RefreshPolicy)
def get_default_refresh_policy(
    environment: Environment, repository: LifecycleRepository = Depends(get_lifecycle_repository)
) -> RefreshPolicy:
    """The environment-wide default policy for `environment`, seeded
    from `DEFAULT_CADENCE_BY_ENVIRONMENT` (the Phase 7 demonstration
    defaults) if it doesn't exist yet."""

    return repository.get_or_create_default_policy(environment)


@router.put("/refresh-policies", response_model=RefreshPolicy)
def upsert_refresh_policy(
    body: UpsertPolicyRequest, repository: LifecycleRepository = Depends(get_lifecycle_repository)
) -> RefreshPolicy:
    """Create or update the refresh policy for `(environment,
    dataset_name)` -- `dataset_name=null` targets the environment-wide
    default. Bumps `policy_version` on update."""

    return repository.upsert_policy(
        environment=body.environment,
        dataset_name=body.dataset_name,
        cadence_type=body.cadence_type,
        interval_days=body.interval_days,
        retention_days=body.retention_days,
        grace_period_days=body.grace_period_days,
        on_demand_allowed=body.on_demand_allowed,
    )


# ----------------------------------------------------------------------
# Environment dataset requests
# ----------------------------------------------------------------------


@router.post("/environment-requests", response_model=EnvironmentDatasetRequest, status_code=201)
def request_dataset_into_environment(
    body: RequestDatasetRequest,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> EnvironmentDatasetRequest:
    """Request a dataset into an environment. Idempotent per
    `(environment, dataset_name)`; points at the dataset's current
    latest ACTIVE version without creating a physical copy -- see
    `LifecycleRepository.request_environment`."""

    try:
        result = repository.request_environment(
            environment=body.environment,
            dataset_name=body.dataset_name,
            requested_by=body.requested_by,
            consumer=body.consumer,
        )
    except NoActiveDatasetVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.ENVIRONMENT_REQUEST_CREATED,
        actor=body.requested_by,
        subject=f"{body.environment.value}:{body.dataset_name}",
        outcome="allowed",
        detail={"request_id": str(result.request_id)},
    )
    return result


@router.get("/environment-requests", response_model=list[EnvironmentDatasetRequest])
def list_environment_requests(
    environment: Environment | None = None,
    dataset_name: str | None = None,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> list[EnvironmentDatasetRequest]:
    return repository.list_requests(environment=environment, dataset_name=dataset_name)


@router.get("/environment-requests/{request_id}", response_model=EnvironmentDatasetRequest)
def get_environment_request(
    request_id: UUID, repository: LifecycleRepository = Depends(get_lifecycle_repository)
) -> EnvironmentDatasetRequest:
    try:
        return repository.get_request(request_id)
    except EnvironmentRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/environment-requests/{request_id}/refresh", response_model=RefreshRunRecord)
def refresh_environment_request(
    request_id: UUID,
    body: RefreshRequestBody,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> RefreshRunRecord:
    """Trigger a refresh (on-demand by default). Rejected with 409 if
    the applicable policy disallows on-demand refresh.

    Phase 11 "duplicate refresh request" failure-injection note: this
    call is safe to repeat -- `LifecycleRepository.refresh` never
    creates a duplicate `EnvironmentDatasetRequestRow` (there is only
    ever one, enforced by a unique constraint on
    `(environment, dataset_name)`) and never creates a duplicate
    `DatasetVersionRow`; two rapid/duplicate calls simply produce two
    `RefreshRunRow` log entries, which is correct (each is a real,
    distinct execution), not corruption. See
    `test_failure_injection.py::test_duplicate_refresh_requests_do_not_corrupt_state`
    and `problems_phase_07.md` P7-2 for the one remaining, honestly
    documented gap this does *not* close (no distributed lock across
    concurrent *scheduler sweeps*, as opposed to this single-request
    endpoint)."""

    try:
        run = repository.refresh(request_id, trigger=body.trigger, triggered_by=body.triggered_by)
    except EnvironmentRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except OnDemandRefreshNotAllowedError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    audit.record(
        event_type=AuditEventType.REFRESH_EXECUTED,
        actor=body.triggered_by,
        subject=str(request_id),
        outcome="allowed" if run.succeeded else "failed",
        detail={"trigger": body.trigger.value, "run_id": str(run.run_id)},
    )
    return run


@router.post("/environment-requests/{request_id}/rollback", response_model=RollbackRecord)
def rollback_environment_request(
    request_id: UUID,
    body: RollbackRequestBody,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> RollbackRecord:
    """Roll one environment's request back to an earlier version of the
    same dataset. Rejected with 409 if the target version is REVOKED.

    Phase 11: requires `body.actor_role` to hold
    `Permission.ROLLBACK_DATASET_VERSION` (`DATA_STEWARD`/
    `PLATFORM_ADMIN`). See `revoke_dataset_version`'s docstring for why
    the denial audit event is committed immediately."""

    try:
        authorize(body.actor_role, Permission.ROLLBACK_DATASET_VERSION)
    except AuthorizationError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=body.performed_by,
            subject=str(request_id),
            outcome="denied",
            detail={"permission": Permission.ROLLBACK_DATASET_VERSION.value, "actor_role": body.actor_role.value},
        )
        session.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    try:
        result = repository.rollback(
            request_id,
            to_version_number=body.to_version_number,
            performed_by=body.performed_by,
            reason=body.reason,
        )
    except EnvironmentRequestNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except CannotSelectRevokedVersionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    audit.record(
        event_type=AuditEventType.DATASET_VERSION_ROLLED_BACK,
        actor=body.performed_by,
        subject=str(request_id),
        outcome="allowed",
        detail={"to_version_number": str(body.to_version_number), "reason": body.reason},
    )
    return result


# ----------------------------------------------------------------------
# Scheduler / orchestration abstraction
# ----------------------------------------------------------------------


@router.get("/scheduler/due", response_model=list[EnvironmentDatasetRequest])
def list_due_refreshes(
    as_of: Annotated[datetime | None, Query()] = None,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> list[EnvironmentDatasetRequest]:
    """What needs refreshing right now -- the read side of the
    `RefreshOrchestrator` abstraction
    (`control_plane.domain.lifecycle.scheduler`), exposed so an external
    scheduler (a cron job, an Airflow sensor, a Databricks Workflow
    trigger) can poll it without needing in-process access to the
    repository. See `docs/adr/0012-refresh-orchestration-abstraction.md`.
    """

    orchestrator = LocalRefreshOrchestrator(repository)
    return orchestrator.due_refreshes(as_of)


@router.post("/scheduler/run-due")
def run_due_refreshes(
    as_of: Annotated[datetime | None, Query()] = None,
    triggered_by: str = "scheduler",
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> dict[str, object]:
    """Execute a SCHEDULED refresh for every currently-due request. This
    is what a real Airflow task / Databricks Workflow job would call
    from inside its own scheduled execution -- see the module docstring
    on `control_plane.domain.lifecycle.scheduler` and ADR-0012."""

    orchestrator = LocalRefreshOrchestrator(repository)
    result = orchestrator.run_due_refreshes(as_of, triggered_by=triggered_by)
    return {
        "as_of": result.as_of,
        "attempted_count": len(result.attempted),
        "succeeded_count": len(result.results),
        "failed_count": len(result.errors),
        "results": [r.model_dump(mode="json") for r in result.results],
        "errors": result.errors,
    }
