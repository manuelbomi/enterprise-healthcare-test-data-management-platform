"""Tests for `control_plane.platform.audit.AuditLogRepository` -- the
first real, DB-backed wiring of the Phase 0 `healthcare_tdm_contracts.AuditEvent`
contract. See `services/control-plane/tests/test_failure_injection.py`
for the end-to-end proof that real lifecycle/governance mutations
actually produce these events over HTTP.
"""

from __future__ import annotations

import pytest
from healthcare_tdm_contracts import AuditEventType
from sqlalchemy.orm import Session

from control_plane.db.models import init_schema, create_sqlite_engine
from control_plane.platform.audit import AuditLogRepository


@pytest.fixture
def session() -> Session:
    engine = create_sqlite_engine(":memory:")
    init_schema(engine)
    from sqlalchemy.orm import sessionmaker

    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as s:
        yield s


def test_record_persists_and_returns_a_typed_event(session: Session) -> None:
    repo = AuditLogRepository(session)
    event = repo.record(
        event_type=AuditEventType.DATASET_VERSION_REVOKED,
        actor="security@example.org",
        subject="some-version-id",
        outcome="allowed",
        detail={"reason": "policy defect"},
    )
    assert event.event_type is AuditEventType.DATASET_VERSION_REVOKED
    assert event.actor == "security@example.org"
    assert event.detail == {"reason": "policy defect"}


def test_list_events_returns_most_recent_first(session: Session) -> None:
    repo = AuditLogRepository(session)
    repo.record(
        event_type=AuditEventType.DATASET_VERSION_REGISTERED,
        actor="a",
        subject="v1",
        outcome="allowed",
    )
    repo.record(
        event_type=AuditEventType.DATASET_VERSION_REVOKED,
        actor="b",
        subject="v1",
        outcome="allowed",
    )
    events = repo.list_events(subject="v1")
    assert len(events) == 2
    assert events[0].event_type is AuditEventType.DATASET_VERSION_REVOKED  # most recent first


def test_list_events_filters_by_event_type(session: Session) -> None:
    repo = AuditLogRepository(session)
    repo.record(event_type=AuditEventType.ACCESS_DENIED, actor="x", subject="s1", outcome="denied")
    repo.record(event_type=AuditEventType.POLICY_APPROVED, actor="y", subject="s2", outcome="allowed")

    denied_only = repo.list_events(event_type=AuditEventType.ACCESS_DENIED)
    assert len(denied_only) == 1
    assert denied_only[0].outcome == "denied"


def test_audit_log_repository_has_no_update_or_delete_method() -> None:
    # Structural enforcement of immutability: there is no code path in
    # this class that could modify or remove a row once written.
    public_methods = {name for name in dir(AuditLogRepository) if not name.startswith("_")}
    assert public_methods == {"record", "list_events"}
