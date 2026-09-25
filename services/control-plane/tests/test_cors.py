"""Tests for the Phase 9 opt-in CORS middleware (`main.py`, `config.py`).

Default (same-origin, no `TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS` set) is
the documented default -- see ADR-0008: the Vite dev server proxies
`/api` to this service, so the browser never makes a cross-origin
request. CORS is opt-in, only for the documented escape hatch
(`frontend/.env.example`'s `VITE_API_BASE_URL`) or a future deployment
shape where the frontend is served from a different origin.
"""

from __future__ import annotations

from fastapi.testclient import TestClient

from control_plane.config import Settings
from control_plane.main import create_app


def test_no_cors_headers_by_default(monkeypatch) -> None:
    monkeypatch.delenv("TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS", raising=False)
    client = TestClient(create_app())
    response = client.get("/api/v1/health", headers={"Origin": "http://example.org"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_headers_present_when_origin_allowed(monkeypatch) -> None:
    monkeypatch.setenv("TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS", "http://127.0.0.1:5174,http://localhost:5174")
    client = TestClient(create_app())
    response = client.get("/api/v1/health", headers={"Origin": "http://127.0.0.1:5174"})
    assert response.status_code == 200
    assert response.headers["access-control-allow-origin"] == "http://127.0.0.1:5174"


def test_cors_rejects_unlisted_origin(monkeypatch) -> None:
    monkeypatch.setenv("TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS", "http://127.0.0.1:5174")
    client = TestClient(create_app())
    response = client.get("/api/v1/health", headers={"Origin": "http://evil.example.org"})
    assert response.status_code == 200
    assert "access-control-allow-origin" not in response.headers


def test_cors_allowed_origins_list_parses_and_strips() -> None:
    settings = Settings(cors_allowed_origins=" http://a.example, http://b.example ,,")
    assert settings.cors_allowed_origins_list == ["http://a.example", "http://b.example"]


def test_cors_allowed_origins_list_empty_by_default() -> None:
    assert Settings().cors_allowed_origins_list == []
