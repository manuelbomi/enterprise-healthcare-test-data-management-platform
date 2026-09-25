"""Phase 12: the governance service's first real test -- proving the
liveness endpoint added in `governance_service.main` actually works,
now that this service is a real, containerizable FastAPI process
rather than an unbuildable scaffold. See `api/health.py`'s module
docstring for why this is deliberately scoped to liveness only."""

from __future__ import annotations

from fastapi.testclient import TestClient

from governance_service.main import create_app


def test_health_endpoint_returns_ok() -> None:
    client = TestClient(create_app())
    response = client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["service"] == "governance-service"
