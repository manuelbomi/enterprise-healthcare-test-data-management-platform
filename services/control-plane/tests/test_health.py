"""Tests for the control plane's health endpoint.

This is the only real behavior in Phase 0, so it is the only thing tested
here. Requires the service's dev dependencies to be installed
(`pip install -e ".[dev]"`), tracked as open item P0-1 in
problems_master.md — not yet run in this environment.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.main import create_app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "control-plane"}
