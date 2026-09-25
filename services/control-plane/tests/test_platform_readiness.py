"""Tests for `control_plane.platform.readiness` and the `/api/v1/ready`
endpoint -- the readiness-vs-liveness distinction Phase 0's `/health`
module docstring promised and this phase finally delivers.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine

from control_plane.db.models import create_sqlite_engine, init_schema
from control_plane.main import create_app
from control_plane.platform.readiness import check_catalog_artifact, check_database, evaluate_readiness
from control_plane.platform.retry import RetryPolicy


def test_check_database_reports_healthy_for_a_reachable_database(tmp_path: Path) -> None:
    engine = create_sqlite_engine(str(tmp_path / "ready.db"))
    init_schema(engine)
    result = check_database(engine)
    assert result.healthy is True
    assert result.required is True


def test_check_database_reports_unhealthy_for_an_unreachable_database() -> None:
    # A SQLite URL pointing at a directory that cannot exist (a file
    # component in the middle of the path) is a real, reliable way to
    # force a genuine connection failure without mocking the DB driver.
    bogus_path = "/this/path/cannot/possibly/exist/on/ci-or-any-machine/ready.db"
    engine = create_engine(f"sqlite:///{bogus_path}")
    result = check_database(engine, retry_policy=RetryPolicy(max_attempts=2, base_delay_seconds=0.01))
    assert result.healthy is False
    assert result.required is True
    # No raw connection-string/credential detail leaked -- only the
    # exception type name, per the module's own documented principle.
    assert bogus_path not in result.detail


def test_check_catalog_artifact_is_not_required(tmp_path: Path) -> None:
    missing = check_catalog_artifact(tmp_path / "does-not-exist.json")
    assert missing.healthy is False
    assert missing.required is False  # informational only, never fails readiness


def test_evaluate_readiness_overall_ready_ignores_optional_check_failures(tmp_path: Path) -> None:
    engine = create_sqlite_engine(str(tmp_path / "ready2.db"))
    init_schema(engine)
    overall, checks = evaluate_readiness(engine=engine, catalog_path=tmp_path / "missing-catalog.json")
    assert overall is True  # DB is reachable; catalog missing is optional
    assert any(c.name == "catalog_artifact" and not c.healthy for c in checks)


def test_ready_endpoint_returns_200_when_database_reachable(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL", f"sqlite:///{tmp_path / 'app-ready.db'}")
    client = TestClient(create_app())
    response = client.get("/api/v1/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert any(c["name"] == "database" and c["healthy"] for c in body["checks"])


def test_health_endpoint_remains_liveness_only_no_dependency_check() -> None:
    # Regression guard for the liveness/readiness split: /health must
    # keep responding even with a deliberately broken DB URL, since it
    # is not supposed to check dependencies at all.
    import os

    old = os.environ.get("TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL")
    os.environ["TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL"] = "sqlite:////this/does/not/exist/x.db"
    try:
        client = TestClient(create_app())
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"
    finally:
        if old is None:
            os.environ.pop("TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL", None)
        else:
            os.environ["TDM_CONTROL_PLANE_LIFECYCLE_DATABASE_URL"] = old
