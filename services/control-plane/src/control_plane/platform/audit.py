"""`AuditLogRepository` -- wires the Phase 0 `healthcare_tdm_contracts.AuditEvent`
contract to a real, append-only, DB-backed store for the first time.

`ARCHITECTURE.md` section 2.4 and `THREAT_MODEL.md` ("Repudiation") both
describe an immutable audit event log as a security/governance-plane
responsibility. Every phase through Phase 10 that produced a
security/governance-relevant action (a masking run, a certification, a
dataset revocation, a policy approval) documented, honestly, that no
such log existed yet to write to (see `problems_phase_03.md` P3-2,
`problems_phase_06.md` P6-2, `problems_phase_07.md` P7-6,
`problems_phase_10.md` P10-2). This module is the first real one.

Scope: this phase wires `AuditLogRepository` into the control plane's
own highest-sensitivity, RBAC-gated mutations (dataset version
revoke/rollback, policy version approve/reject) plus the ordinary
lifecycle/governance mutations that create durable state (dataset
version registration, environment requests, refreshes, consumer
requests) -- see `control_plane.api.v1.lifecycle` and
`control_plane.api.v1.governance` for the call sites. It does **not**
reach into `data_plane` (ADR-0003: plane separation) -- a masking or
certification run still only produces its own signed
`certification_report.json` (Phase 6) or `masking_run_summary.json`
(Phase 3); wiring those into this same log is future work (see
`problems_phase_11.md` P11-5).

Immutability: this class has no `update`/`delete` method of any kind.
That is the entire enforcement mechanism -- there is no code path in
this codebase that can modify or remove a row once written, the same
"the application layer exposes no update/delete path" property
`THREAT_MODEL.md` requires.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from healthcare_tdm_contracts import AuditEvent, AuditEventType
from sqlalchemy import select
from sqlalchemy.orm import Session

from control_plane.db.models import AuditEventRow


def _now() -> datetime:
    return datetime.now(timezone.utc)


class AuditLogRepository:
    """Append-only reader/writer for `AuditEventRow`. One instance per
    request/unit-of-work, the same convention `LifecycleRepository` and
    `GovernanceRepository` use -- cheap to construct, holds only the
    session reference, so it can share a request's transaction (a
    denied mutation and its `ACCESS_DENIED` audit event, or a permitted
    mutation and its own audit event, commit -- or roll back -- together;
    see `control_plane.api.v1.lifecycle`'s handlers for the one
    deliberate exception, an early `session.commit()` on a denial so
    the denial record survives even though the request as a whole still
    returns HTTP 403)."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self,
        *,
        event_type: AuditEventType,
        actor: str,
        subject: str,
        outcome: str,
        detail: dict[str, str] | None = None,
    ) -> AuditEvent:
        """Append one immutable audit event. Returns the persisted
        event as a typed contract object (never a raw ORM row)."""

        row = AuditEventRow(
            event_id=str(uuid4()),
            event_type=event_type.value,
            actor=actor,
            subject=subject,
            outcome=outcome,
            detail_json=json.dumps(detail or {}),
            occurred_at=_now(),
        )
        self._session.add(row)
        self._session.flush()
        return self._to_contract(row)

    def list_events(
        self,
        *,
        event_type: AuditEventType | None = None,
        subject: str | None = None,
        actor: str | None = None,
        limit: int = 200,
    ) -> list[AuditEvent]:
        """List events, most recent first. Read-only -- there is no
        corresponding write path other than `record()`."""

        stmt = select(AuditEventRow)
        if event_type is not None:
            stmt = stmt.where(AuditEventRow.event_type == event_type.value)
        if subject is not None:
            stmt = stmt.where(AuditEventRow.subject == subject)
        if actor is not None:
            stmt = stmt.where(AuditEventRow.actor == actor)
        stmt = stmt.order_by(AuditEventRow.occurred_at.desc()).limit(limit)
        rows = self._session.scalars(stmt).all()
        return [self._to_contract(row) for row in rows]

    def _to_contract(self, row: AuditEventRow) -> AuditEvent:
        return AuditEvent(
            event_id=row.event_id,
            event_type=AuditEventType(row.event_type),
            actor=row.actor,
            subject=row.subject,
            outcome=row.outcome,
            detail=json.loads(row.detail_json or "{}"),
            occurred_at=row.occurred_at,
        )


__all__ = ["AuditLogRepository"]
