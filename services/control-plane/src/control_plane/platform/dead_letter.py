"""`DeadLetterStore` -- a durable, queryable record of individually-
isolated job/sweep failures.

None of the pipeline stages through Phase 10 had a dead-letter concept
at all. The one place in this codebase that already isolates one
item's failure from a batch --
`control_plane.domain.lifecycle.scheduler.LocalRefreshOrchestrator.run_due_refreshes`,
per `docs/adr/0012-refresh-orchestration-abstraction.md`'s "isolate one
request's failure from the others" principle -- only ever reported that
failure back to the single caller of that one sweep
(`RefreshSweepResult.errors`, an in-memory dict that disappears the
moment the HTTP response is sent). This module gives that failure a
durable home: an operator (or a future alerting job) can query "what
has failed recently and why" without having been the one synchronous
caller that triggered the failing sweep.

Distinct from the audit log (`control_plane.platform.audit`): the audit
log records *actions taken* (including successful ones); the
dead-letter store records *things that failed*, with enough detail to
retry or investigate. A single failed refresh writes to *both* --
see `control_plane.domain.lifecycle.scheduler` for the call site.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from control_plane.db.models import DeadLetterEventRow


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DeadLetterRecord:
    """A plain, typed read-model for one dead-letter entry -- kept
    local to this module (not promoted to `libs/contracts`) since
    nothing outside `services/control-plane` consumes it yet; see
    `problems_phase_11.md` for the honest scope boundary."""

    __slots__ = ("dead_letter_id", "event_type", "subject", "reason", "payload", "occurred_at")

    def __init__(
        self,
        *,
        dead_letter_id: str,
        event_type: str,
        subject: str,
        reason: str,
        payload: dict[str, str],
        occurred_at: datetime,
    ) -> None:
        self.dead_letter_id = dead_letter_id
        self.event_type = event_type
        self.subject = subject
        self.reason = reason
        self.payload = payload
        self.occurred_at = occurred_at


class DeadLetterStore:
    """Append-only reader/writer for `DeadLetterEventRow`. One instance
    per request/unit-of-work, same convention as `AuditLogRepository`."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(
        self, *, event_type: str, subject: str, reason: str, payload: dict[str, str] | None = None
    ) -> DeadLetterRecord:
        row = DeadLetterEventRow(
            dead_letter_id=str(uuid4()),
            event_type=event_type,
            subject=subject,
            reason=reason,
            payload_json=json.dumps(payload or {}),
            occurred_at=_now(),
        )
        self._session.add(row)
        self._session.flush()
        return self._to_record(row)

    def list_events(self, *, event_type: str | None = None, limit: int = 200) -> list[DeadLetterRecord]:
        stmt = select(DeadLetterEventRow)
        if event_type is not None:
            stmt = stmt.where(DeadLetterEventRow.event_type == event_type)
        stmt = stmt.order_by(DeadLetterEventRow.occurred_at.desc()).limit(limit)
        return [self._to_record(row) for row in self._session.scalars(stmt).all()]

    def _to_record(self, row: DeadLetterEventRow) -> DeadLetterRecord:
        return DeadLetterRecord(
            dead_letter_id=row.dead_letter_id,
            event_type=row.event_type,
            subject=row.subject,
            reason=row.reason,
            payload=json.loads(row.payload_json or "{}"),
            occurred_at=row.occurred_at,
        )


__all__ = ["DeadLetterRecord", "DeadLetterStore"]
