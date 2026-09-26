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

import logging
import re
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
from control_plane.domain.governance import GovernanceRepository, MaskingPolicyVersionNotFoundError
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
from control_plane.platform.auth import AuthenticatedActor, get_current_actor
from control_plane.platform.rbac import AuthorizationError, Permission, authorize
from control_plane.platform.scheduler_lock import SchedulerLockHeldError, scheduler_sweep_lock

router = APIRouter(prefix="/lifecycle", tags=["lifecycle"])

_scheduler_logger = logging.getLogger("control_plane.lifecycle.scheduler")


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


def get_governance_repository_for_lifecycle(session: Session = Depends(get_db_session)) -> GovernanceRepository:
    """A second dependency resolving `GovernanceRepository` against the
    exact same request-scoped `Session` as `get_lifecycle_repository`
    above -- defined locally (rather than imported from
    `api/v1/governance.py`) to avoid a circular import between the two
    routers. Used only by `register_dataset_version_governed` (Phase
    18A, P1-8) below."""

    return GovernanceRepository(session)


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
    #: Phase 11: checked via `control_plane.platform.rbac.authorize`
    #: against `Permission.REVOKE_DATASET_VERSION` before the revocation
    #: is attempted. Not a no-op -- see `test_failure_injection.py`'s
    #: RBAC-rejection test. Phase 18A (`docs/problems/problems_final_review.md` P0-1):
    #: the role checked is no longer a field on this request body -- it
    #: is derived from the caller's verified bearer token instead (see
    #: `revoke_dataset_version`'s `actor: AuthenticatedActor` parameter
    #: below and `control_plane.platform.auth`'s module docstring).


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


class RecordDatasetVersionAccessRequest(BaseModel):
    """Phase 13: record that someone accessed/used a provisioned dataset
    version -- the "who accessed it" requirement `docs/problems/problems_phase_13.md`
    found genuinely unmet (only ACCESS_DENIED was ever wired; nothing
    recorded a successful access). Self-reported, like every other
    actor field in this service (`accessed_by` is not verified against
    a real identity provider -- see `control_plane.platform.rbac`'s
    module docstring for the same honest caveat on `revoked_by`/
    `performed_by`)."""

    accessed_by: str
    environment: Environment | None = Field(
        default=None, description="Which environment's copy was accessed, if known."
    )
    purpose: str = Field(default="", description="Free-text reason, e.g. 'QA test run', 'compliance review'.")


class RollbackRequestBody(BaseModel):
    to_version_number: int = Field(..., ge=1)
    performed_by: str
    reason: str
    #: Phase 11: checked against `Permission.ROLLBACK_DATASET_VERSION`.
    #: Phase 18A: no longer a field here -- see `RevokeVersionRequest`'s
    #: docstring above.


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
    `docs/problems/problems_phase_11.md`'s "Resolved problems").

    **This is the UNGOVERNED/direct registration path** -- it does not
    verify that `certification_report.masking_policy_name`/
    `masking_policy_version` were ever actually drafted/approved through
    Phase 10's governance workflow (see `docs/problems/problems_phase_10.md` P10-1 /
    `docs/problems/problems_final_review.md` P1-8, and
    `docs/adr/0019-governed-vs-ungoverned-dataset-version-registration.md`).
    Use `POST /dataset-versions/governed` below instead when governance
    enforcement is required."""

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


_FINAL_ROW_COUNT_RE = re.compile(r"final=(\d+)")


def _independently_derived_row_counts(row_count_reconciliation: dict[str, str]) -> dict[str, int]:
    """Phase 18B (`docs/problems/problems_final_review.md` P2-4): parse the "final=<N>"
    component out of each entity's entry in
    `CertificationReport.row_count_reconciliation` -- a human-readable
    trail built by `data_plane.certification.pipeline` from a real read
    of the final estate on disk (`final_estate.row_counts()`), not
    caller-supplied. This is what lets `register_dataset_version_governed`
    below independently cross-check the caller-supplied `row_counts`
    parameter against a number the certification pipeline itself already
    measured, for exactly the entities the report's own trail covers --
    mirroring ADR-0019's "never trust the caller's claim, re-derive it
    from an already-governed source" pattern, applied here to row counts
    instead of policy approval.

    Entities with no parseable "final=" entry (e.g. a hand-built report
    with no `row_count_reconciliation` at all) are simply absent from the
    returned dict -- this function never invents a count it cannot
    actually read back out of the report."""

    derived: dict[str, int] = {}
    for entity, trail in row_count_reconciliation.items():
        match = _FINAL_ROW_COUNT_RE.search(trail)
        if match is not None:
            derived[entity] = int(match.group(1))
    return derived


@router.post("/dataset-versions/governed", response_model=DatasetVersion, status_code=201)
def register_dataset_version_governed(
    body: RegisterDatasetVersionRequest,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    governance: GovernanceRepository = Depends(get_governance_repository_for_lifecycle),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> DatasetVersion:
    """Phase 18A (`docs/problems/problems_final_review.md` P1-8, now resolved): the
    GOVERNED counterpart to `register_dataset_version` above.

    Before Phase 18A, nothing in this service verified that a dataset
    version's claimed masking policy had ever actually been drafted,
    submitted, and approved through Phase 10's governance workflow --
    `register_dataset_version` would happily register a version
    certified against a hand-built `MaskingPolicy` that bypassed
    governance entirely, purely by convention (every demo script always
    passed the actually-approved policy object, but nothing enforced
    that discipline in code).

    This endpoint closes that gap by independently re-deriving, from
    `GovernanceRepository` (never trusting the certification report's
    own claim), whether `body.certification_report.masking_policy_name`/
    `masking_policy_version` actually match the currently-APPROVED
    `MaskingPolicyVersion` for that policy name, and rejecting
    registration with HTTP 409 if not.

    **Why the plain `register_dataset_version` endpoint above still
    exists, unchanged, rather than being replaced outright:** making
    governance enforcement a breaking change on the one endpoint every
    pre-Phase-18A demo script, tutorial chapter, and test already calls
    would be a disproportionately large blast radius for this phase. See
    `docs/adr/0019-governed-vs-ungoverned-dataset-version-registration.md`
    for the full reasoning. `register_dataset_version` is now
    explicitly, honestly documented as the UNGOVERNED/direct path (its
    own docstring is unchanged in behavior but a reader following this
    docstring's cross-reference will find that framing here); this
    endpoint is the GOVERNED path a real deployment relying on Phase
    10's governance workflow to mean something should use instead.
    """

    try:
        approved = governance.get_approved_policy_version(body.certification_report.masking_policy_name)
    except MaskingPolicyVersionNotFoundError as exc:
        raise HTTPException(
            status_code=409,
            detail=(
                f"No APPROVED MaskingPolicyVersion exists for policy_name="
                f"{body.certification_report.masking_policy_name!r}. Governed registration "
                "requires an approved Phase 10 policy version -- draft, submit, and approve one "
                "first (POST /api/v1/governance/policy-versions, .../submit, .../approve), or use "
                "POST /api/v1/lifecycle/dataset-versions (the ungoverned/direct path) if bypassing "
                f"governance is intentional for this registration. ({exc})"
            ),
        ) from exc

    # Phase 18B (`docs/problems/problems_final_review.md` P2-4, now partially resolved
    # for the GOVERNED path -- see `_independently_derived_row_counts`'s
    # own docstring): cross-check `body.row_counts` against whatever the
    # certification pipeline's own `row_count_reconciliation` trail
    # already measured, for the entities it covers. `size_bytes` has no
    # equivalent already-measured source anywhere in `CertificationReport`
    # -- re-deriving it would need a real control-plane-side storage
    # adapter (`docs/problems/problems_final_review.md` P2-5), which remains out of
    # scope; this closes the smaller, genuinely-already-available half
    # of the gap, not the whole thing.
    derived_row_counts = _independently_derived_row_counts(
        body.certification_report.row_count_reconciliation
    )
    mismatches = {
        entity: (body.row_counts.get(entity), derived_count)
        for entity, derived_count in derived_row_counts.items()
        if entity in body.row_counts and body.row_counts[entity] != derived_count
    }
    if mismatches:
        raise HTTPException(
            status_code=409,
            detail=(
                "row_counts does not match the certification report's own "
                f"row_count_reconciliation trail: {mismatches} (entity -> "
                "(caller-supplied, independently-derived from the report)). Governed "
                "registration refuses a row_counts claim that contradicts what the "
                "certification pipeline itself already measured for the entities its "
                "own trail covers."
            ),
        )

    if approved.policy_version != body.certification_report.masking_policy_version:
        raise HTTPException(
            status_code=409,
            detail=(
                f"certification_report.masking_policy_version="
                f"{body.certification_report.masking_policy_version} does not match the "
                f"currently-APPROVED policy_version={approved.policy_version} for policy_name="
                f"{body.certification_report.masking_policy_name!r}. This dataset was certified "
                "against a masking policy version that is not (or is no longer) the governed, "
                "approved one -- registration refused."
            ),
        )

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
        subject=str(version.version_id),
        outcome="allowed",
        detail={
            "dataset_name": body.dataset_name,
            "version_number": str(version.version_number),
            "storage_uri": body.storage_uri,
            "governed": "true",
            "approved_policy_version_id": str(approved.policy_version_id),
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
    actor: AuthenticatedActor = Depends(get_current_actor),
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> DatasetVersion:
    """Revoke a version. Environments already pointed at it are left
    alone (see `DatasetVersionStatus.REVOKED`'s docstring); a revoked
    version can never again be selected by `request_environment`,
    `refresh`, or `rollback`.

    Phase 11: requires the caller to hold `Permission.REVOKE_DATASET_VERSION`
    (only `COMPLIANCE_APPROVER`/`PLATFORM_ADMIN` do -- see
    `control_plane.platform.rbac`). An unauthorized attempt is rejected
    with HTTP 403 *before* the repository is called at all, and is
    itself recorded as an `ACCESS_DENIED` audit event (committed
    immediately so the denial record survives the exception this
    handler then raises -- see `control_plane.platform.audit`'s module
    docstring for why this is one of the handlers in this router that
    calls `session.commit()` directly instead of relying on
    `session_scope`'s end-of-request commit).

    Phase 18A (`docs/problems/problems_final_review.md` P0-1): `actor.role` is now a
    verified claim from the caller's bearer token
    (`Depends(get_current_actor)`), not a caller-supplied,
    unverified request-body field -- see
    `control_plane.platform.auth`'s module docstring. Requires
    `Authorization: Bearer <token>` from `POST /api/v1/auth/login`."""

    try:
        authorize(actor.role, Permission.REVOKE_DATASET_VERSION)
    except AuthorizationError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=actor.username,
            subject=str(version_id),
            outcome="denied",
            detail={"permission": Permission.REVOKE_DATASET_VERSION.value, "actor_role": actor.role.value},
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
        # Phase 18B (`docs/problems/problems_final_review.md` P2-13): the audit
        # trail's `actor` field now records the verified bearer-token
        # identity (`actor.username`), not the unverified
        # `body.revoked_by` free-text field -- `body.revoked_by` itself
        # is unchanged (still recorded on the domain-level
        # `DatasetVersionRow`, still free text). Closes the
        # *audit-trail* half of this gap for this RBAC-gated endpoint
        # specifically, not every caller-supplied attribution field
        # platform-wide.
        event_type=AuditEventType.DATASET_VERSION_REVOKED,
        actor=actor.username,
        subject=str(version_id),
        outcome="allowed",
        detail={"reason": body.reason, "actor_role": actor.role.value, "revoked_by": body.revoked_by},
    )
    return version


@router.post("/dataset-versions/{version_id}/access", response_model=DatasetVersion)
def record_dataset_version_access(
    version_id: UUID,
    body: RecordDatasetVersionAccessRequest,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
) -> DatasetVersion:
    """Phase 13: record that `body.accessed_by` accessed/used this
    dataset version. Not RBAC-gated (see `docs/problems/problems_phase_13.md` P13-3)
    -- any caller may self-report an access, the same way every other
    unrestricted lifecycle mutation in this router works. Returns the
    dataset version unchanged (this call has no state effect other than
    the audit record) so a caller can confirm which version it just
    recorded access against."""

    try:
        version = repository.get_version(version_id)
    except DatasetVersionNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audit.record(
        event_type=AuditEventType.DATASET_VERSION_ACCESSED,
        actor=body.accessed_by,
        subject=str(version_id),
        outcome="allowed",
        detail={
            "environment": body.environment.value if body.environment else "",
            "purpose": body.purpose,
        },
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
    and `docs/problems/problems_phase_07.md` P7-2 for the one remaining, honestly
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
    actor: AuthenticatedActor = Depends(get_current_actor),
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> RollbackRecord:
    """Roll one environment's request back to an earlier version of the
    same dataset. Rejected with 409 if the target version is REVOKED.

    Phase 11: requires the caller to hold
    `Permission.ROLLBACK_DATASET_VERSION` (`DATA_STEWARD`/
    `PLATFORM_ADMIN`). See `revoke_dataset_version`'s docstring for why
    the denial audit event is committed immediately, and for Phase 18A's
    switch from a caller-supplied `actor_role` field to a verified
    bearer token (`Depends(get_current_actor)`)."""

    try:
        authorize(actor.role, Permission.ROLLBACK_DATASET_VERSION)
    except AuthorizationError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=actor.username,
            subject=str(request_id),
            outcome="denied",
            detail={"permission": Permission.ROLLBACK_DATASET_VERSION.value, "actor_role": actor.role.value},
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
        # Phase 18B (`docs/problems/problems_final_review.md` P2-13): see
        # `revoke_dataset_version`'s identical comment above.
        event_type=AuditEventType.DATASET_VERSION_ROLLED_BACK,
        actor=actor.username,
        subject=str(request_id),
        outcome="allowed",
        detail={
            "to_version_number": str(body.to_version_number),
            "reason": body.reason,
            "actor_role": actor.role.value,
            "performed_by": body.performed_by,
        },
    )
    return result


@router.get("/refresh-runs", response_model=list[RefreshRunRecord])
def list_refresh_runs(
    dataset_name: str | None = None,
    request_id: UUID | None = None,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> list[RefreshRunRecord]:
    """Phase 13: full refresh history (most recent first), optionally
    filtered by `dataset_name` and/or `request_id` -- the read side
    `docs/problems/problems_phase_13.md` (issue 2) found missing: `refresh()` above
    only ever returned the one run it had just created."""

    return repository.list_refresh_runs(dataset_name=dataset_name, request_id=request_id)


@router.get("/rollback-events", response_model=list[RollbackRecord])
def list_rollback_events(
    dataset_name: str | None = None,
    request_id: UUID | None = None,
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
) -> list[RollbackRecord]:
    """Phase 13: full rollback history (most recent first), optionally
    filtered by `dataset_name` and/or `request_id` -- same gap as
    `list_refresh_runs` above, for `rollback()`."""

    return repository.list_rollback_events(dataset_name=dataset_name, request_id=request_id)


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
    actor: AuthenticatedActor = Depends(get_current_actor),
    repository: LifecycleRepository = Depends(get_lifecycle_repository),
    audit: AuditLogRepository = Depends(get_audit_log),
    session: Session = Depends(get_db_session),
) -> dict[str, object]:
    """Execute a SCHEDULED refresh for every currently-due request. This
    is what a real Airflow task / Databricks Workflow job would call
    from inside its own scheduled execution -- see the module docstring
    on `control_plane.domain.lifecycle.scheduler` and ADR-0012.

    Phase 18A (`docs/problems/problems_final_review.md` P1-2, now resolved): this
    endpoint previously had no RBAC check at all, despite having a
    strictly larger blast radius (every currently-due request, in one
    call) than any of the four endpoints RBAC already gated. It now
    requires `Permission.RUN_SCHEDULER` (`PLATFORM_ADMIN` only -- see
    `control_plane.platform.rbac`), verified from a real bearer token
    the same way `revoke_dataset_version`/`rollback_environment_request`
    are. `triggered_by` is no longer a caller-supplied, unverified query
    parameter (previously defaulting to the literal string
    `"scheduler"` regardless of who actually called this) -- it is now
    always the verified actor's username. A real deployment should
    still additionally restrict this endpoint at the network level to a
    trusted internal scheduler (see the module docstring on
    `control_plane.domain.lifecycle.scheduler`); RBAC is defense in
    depth, not a substitute for that.

    Phase 18B (`docs/problems/problems_final_review.md` P2-2, now resolved): two
    concurrent calls to this endpoint used to have no application-level
    mutual exclusion at all -- both would independently compute "what's
    due" and could both attempt to refresh the same request. It now
    acquires `control_plane.platform.scheduler_lock`'s real,
    database-enforced sweep lock before calling the orchestrator; a
    second, overlapping call is refused with 409 rather than allowed to
    race the first."""

    try:
        authorize(actor.role, Permission.RUN_SCHEDULER)
    except AuthorizationError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=actor.username,
            subject="lifecycle/scheduler/run-due",
            outcome="denied",
            detail={"permission": Permission.RUN_SCHEDULER.value, "actor_role": actor.role.value},
        )
        session.commit()
        raise HTTPException(status_code=403, detail=str(exc)) from exc

    orchestrator = LocalRefreshOrchestrator(repository)
    try:
        with scheduler_sweep_lock(session, acquired_by=actor.username):
            result = orchestrator.run_due_refreshes(as_of, triggered_by=actor.username)
    except SchedulerLockHeldError as exc:
        audit.record(
            event_type=AuditEventType.ACCESS_DENIED,
            actor=actor.username,
            subject="lifecycle/scheduler/run-due",
            outcome="denied",
            detail={"reason": "scheduler_lock_held", "held_by": exc.held_by},
        )
        session.commit()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    # Phase 18A (P1-5): a real job-event log line -- the request-level
    # middleware in main.py already logs "this endpoint was called";
    # this is the additional, job-specific event (how many requests
    # were swept, how many succeeded/failed) a real scheduled job run
    # is exactly the kind of thing `ARCHITECTURE.md` section 3.3's
    # observability claim was about.
    _scheduler_logger.info(
        "scheduler sweep completed",
        extra={
            "triggered_by": actor.username,
            "attempted_count": len(result.attempted),
            "succeeded_count": len(result.results),
            "failed_count": len(result.errors),
        },
    )
    return {
        "as_of": result.as_of,
        "attempted_count": len(result.attempted),
        "succeeded_count": len(result.results),
        "failed_count": len(result.errors),
        "results": [r.model_dump(mode="json") for r in result.results],
        "errors": result.errors,
    }
