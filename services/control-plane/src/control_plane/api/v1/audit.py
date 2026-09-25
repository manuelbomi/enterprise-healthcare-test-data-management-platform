"""Read-only endpoint over the Phase 11 audit event log
(`control_plane.platform.audit`).

Deliberately read-only -- there is no `POST`/`PUT`/`DELETE` route in
this router, matching `AuditLogRepository`'s own append-only-by-
construction design (see its module docstring). Every write happens as
a side effect of the lifecycle/governance mutation it documents
(`api/v1/lifecycle.py`, `api/v1/governance.py`), never directly through
this router.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends
from healthcare_tdm_contracts import AuditEvent, AuditEventType
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.platform.audit import AuditLogRepository

router = APIRouter(prefix="/audit", tags=["audit"])


def get_audit_repository(session: Session = Depends(get_db_session)) -> AuditLogRepository:
    return AuditLogRepository(session)


@router.get("/events", response_model=list[AuditEvent])
def list_audit_events(
    event_type: AuditEventType | None = None,
    subject: str | None = None,
    actor: str | None = None,
    limit: int = 200,
    repository: AuditLogRepository = Depends(get_audit_repository),
) -> list[AuditEvent]:
    """List audit events, most recent first. Optionally filter by
    `event_type`, `subject` (e.g. a dataset version id), or `actor`."""

    return repository.list_events(event_type=event_type, subject=subject, actor=actor, limit=limit)


__all__ = ["get_audit_repository", "router"]
