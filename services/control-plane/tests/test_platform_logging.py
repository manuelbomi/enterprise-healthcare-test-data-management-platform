"""Tests for `control_plane.platform.logging_config` and the request
logging middleware wired into `main.create_app` (Phase 18A, resolves
`docs/problems/problems_final_review.md` P1-5: "`ARCHITECTURE.md`'s observability
claim is 100% unimplemented ... `log_level` config is dead code").

Proves real behavior, not just that the module imports cleanly: a real
HTTP request through a real `TestClient` produces a real JSON log line
with the expected structured fields, and `log_level` actually controls
what gets emitted.
"""

from __future__ import annotations

import json
import logging

import pytest
from fastapi.testclient import TestClient

from control_plane.main import create_app
from control_plane.platform.logging_config import (
    JsonFormatter,
    configure_logging,
    new_correlation_id,
    set_correlation_id,
)


@pytest.fixture
def client() -> TestClient:
    return TestClient(create_app())


def _capture_json_logs(logger_name: str) -> tuple[logging.Handler, list[str]]:
    lines: list[str] = []

    class _CollectingHandler(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            lines.append(self.format(record))

    handler = _CollectingHandler()
    handler.setFormatter(JsonFormatter())
    logging.getLogger(logger_name).addHandler(handler)
    return handler, lines


def test_json_formatter_produces_valid_json_with_the_expected_fields() -> None:
    logger = logging.getLogger("control_plane.test.formatter")
    # Explicit level: this ad hoc test logger must not depend on
    # whatever the ROOT logger's level happens to be left at by other
    # tests/fixtures in the same process (e.g. `configure_logging` or
    # Alembic's own `fileConfig` -- see `migrations/env.py`'s note on
    # `disable_existing_loggers=False`) -- a real app logger relies on
    # `configure_logging` for this; a standalone unit test of the
    # formatter should not.
    logger.setLevel(logging.INFO)
    handler, lines = _capture_json_logs("control_plane.test.formatter")
    try:
        set_correlation_id("test-correlation-id")
        logger.info("something happened", extra={"widget_count": 3})
    finally:
        logger.removeHandler(handler)

    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["message"] == "something happened"
    assert payload["level"] == "INFO"
    assert payload["logger"] == "control_plane.test.formatter"
    assert payload["correlation_id"] == "test-correlation-id"
    assert payload["widget_count"] == 3
    assert "timestamp" in payload


def test_new_correlation_id_produces_a_distinct_value_each_call() -> None:
    a = new_correlation_id()
    b = new_correlation_id()
    assert a != b
    assert a and b


def test_configure_logging_sets_the_root_logger_level() -> None:
    configure_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING
    configure_logging("DEBUG")
    assert logging.getLogger().level == logging.DEBUG
    # Restore a sane default so this test doesn't leak state that
    # silences other tests' log output.
    configure_logging("INFO")


def test_configure_logging_is_idempotent_and_does_not_accumulate_handlers() -> None:
    configure_logging("INFO")
    first_count = len(logging.getLogger().handlers)
    configure_logging("INFO")
    configure_logging("INFO")
    assert len(logging.getLogger().handlers) == first_count


def test_a_real_http_request_emits_a_structured_json_log_line_with_a_correlation_id(
    client: TestClient,
) -> None:
    handler, lines = _capture_json_logs("control_plane.request")
    try:
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert "X-Correlation-Id" in response.headers
    finally:
        logging.getLogger("control_plane.request").removeHandler(handler)

    assert lines, "the request-logging middleware must emit at least one log line"
    payload = json.loads(lines[-1])
    assert payload["message"] == "request completed"
    assert payload["http_method"] == "GET"
    assert payload["http_path"] == "/api/v1/health"
    assert payload["http_status_code"] == 200
    assert isinstance(payload["duration_ms"], (int, float))
    assert payload["correlation_id"] == response.headers["X-Correlation-Id"]


def test_an_incoming_correlation_id_header_is_propagated_not_replaced(client: TestClient) -> None:
    response = client.get("/api/v1/health", headers={"X-Correlation-Id": "caller-supplied-id-123"})
    assert response.headers["X-Correlation-Id"] == "caller-supplied-id-123"


def test_scheduler_run_due_emits_a_real_job_event_log_line(client: TestClient) -> None:
    from conftest import auth_header
    from control_plane.platform.rbac import Role

    handler, lines = _capture_json_logs("control_plane.lifecycle.scheduler")
    try:
        response = client.post(
            "/api/v1/lifecycle/scheduler/run-due", headers=auth_header(client, Role.PLATFORM_ADMIN)
        )
        assert response.status_code == 200
    finally:
        logging.getLogger("control_plane.lifecycle.scheduler").removeHandler(handler)

    assert lines, "run_due_refreshes must emit a real job-event log line"
    payload = json.loads(lines[-1])
    assert payload["message"] == "scheduler sweep completed"
    assert "succeeded_count" in payload
    assert "failed_count" in payload
    assert "triggered_by" in payload
