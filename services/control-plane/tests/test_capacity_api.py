"""Tests for the capacity-planning API (`api/v1/capacity.py`), exercised
through a real FastAPI `TestClient`, mirroring `test_lifecycle_api.py`'s
dependency-override pattern (`get_db_session` overridden to a fresh
temporary SQLite file per test) -- both routers share that same
dependency, so overriding it once covers both.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app

from conftest import make_certified_report


def _client(db_path: Path) -> TestClient:
    engine = create_sqlite_engine(str(db_path))
    factory = build_session_factory(engine)

    def _override() -> Iterator[Session]:
        with session_scope(factory) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    return TestClient(app)


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    return _client(tmp_path / "lifecycle.db")


def _register_version(client: TestClient, dataset_name: str = "claims", size_bytes: int = 1_000) -> dict:
    report = make_certified_report(dataset_name=dataset_name)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": dataset_name,
            "certification_report": json.loads(report.model_dump_json()),
            "storage_uri": f"data/tmp/{dataset_name}",
            "size_bytes": size_bytes,
            "row_counts": {"member": 10, "claim": 40},
            "created_by": "steward@example.org",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def _request_environment(client: TestClient, environment: str, dataset_name: str = "claims") -> dict:
    response = client.post(
        "/api/v1/lifecycle/environment-requests",
        json={"environment": environment, "dataset_name": dataset_name, "requested_by": "a"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_dataset_version_footprint_endpoint(client: TestClient) -> None:
    version = _register_version(client)
    resp = client.get(f"/api/v1/capacity/dataset-versions/{version['version_id']}/footprint")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["storage_footprint_bytes"] == 1_000
    assert body["total_row_count"] == 50
    assert body["physical_copy_count"] == 1


def test_dataset_version_footprint_404(client: TestClient) -> None:
    resp = client.get("/api/v1/capacity/dataset-versions/00000000-0000-0000-0000-000000000000/footprint")
    assert resp.status_code == 404


def test_environment_capacity_demand_endpoint(client: TestClient) -> None:
    _register_version(client)
    request = _request_environment(client, "qa")
    resp = client.get(f"/api/v1/capacity/environment-requests/{request['request_id']}/demand")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["refresh_cadence_type"] == "weekly"
    assert body["refresh_interval_days"] == 7
    assert body["attributed_storage_bytes"] == 1_000


def test_environment_capacity_demand_404(client: TestClient) -> None:
    resp = client.get("/api/v1/capacity/environment-requests/00000000-0000-0000-0000-000000000000/demand")
    assert resp.status_code == 404


def test_capacity_plan_endpoint_real_naive_vs_shared(client: TestClient) -> None:
    _register_version(client, dataset_name="claims", size_bytes=2_000)
    for env in ["dev", "qa", "sit"]:
        _request_environment(client, env, dataset_name="claims")

    resp = client.get("/api/v1/capacity/plan", params={"dataset_name": "claims"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["environment_count"] == 3
    assert body["distinct_dataset_version_count"] == 1
    assert body["naive_total_storage_bytes"] == 6_000
    assert body["shared_total_storage_bytes"] == 2_000
    assert body["storage_savings_bytes"] == 4_000
    assert body["storage_savings_pct"] == pytest.approx(4_000 / 6_000)


def test_vacuum_candidates_endpoint(client: TestClient) -> None:
    version = _register_version(client, dataset_name="claims")
    resp = client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "superseded", "revoked_by": "sec@example.org"},
    )
    assert resp.status_code == 200, resp.text

    resp = client.get("/api/v1/capacity/vacuum-candidates", params={"dataset_name": "claims"})
    assert resp.status_code == 200, resp.text
    candidates = resp.json()
    assert len(candidates) == 1
    assert candidates[0]["version_id"] == version["version_id"]
    assert candidates[0]["reclaimable_bytes"] == 1_000


def test_vacuum_candidates_excludes_still_referenced(client: TestClient) -> None:
    version = _register_version(client, dataset_name="claims")
    _request_environment(client, "dev", dataset_name="claims")
    client.post(
        f"/api/v1/lifecycle/dataset-versions/{version['version_id']}/revoke",
        json={"reason": "policy defect", "revoked_by": "sec@example.org"},
    )
    resp = client.get("/api/v1/capacity/vacuum-candidates", params={"dataset_name": "claims"})
    assert resp.json() == []


def test_illustrative_plan_get_matches_roadmap_example(client: TestClient) -> None:
    resp = client.get("/api/v1/capacity/illustrative-plan")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tb = 10**12
    assert body["naive_total_bytes"] == 140 * tb
    assert body["shared_total_bytes"] == 115 * tb
    assert body["savings_bytes"] == 25 * tb


def test_illustrative_plan_get_with_custom_baseline(client: TestClient) -> None:
    resp = client.get("/api/v1/capacity/illustrative-plan", params={"production_baseline_tb": 10})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    tb = 10**12
    assert body["naive_total_bytes"] == 14 * tb


def test_illustrative_plan_post_with_custom_scenario(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/capacity/illustrative-plan",
        json={
            "production_baseline_bytes": 1_000,
            "requirements": [
                {"environment": "dev", "target_pct_of_production": 0.2, "share_tier": "only"},
                {"environment": "qa", "target_pct_of_production": 0.2, "share_tier": "only"},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["naive_total_bytes"] == 400
    assert body["shared_total_bytes"] == 200
    assert body["savings_pct"] == pytest.approx(0.5)


def test_illustrative_plan_post_rejects_invalid_percentage(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/capacity/illustrative-plan",
        json={
            "production_baseline_bytes": 1_000,
            "requirements": [{"environment": "dev", "target_pct_of_production": 1.5}],
        },
    )
    assert resp.status_code == 422
