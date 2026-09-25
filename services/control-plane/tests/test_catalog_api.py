"""Tests for the catalog API (`api/v1/catalog.py`), exercised through a
real FastAPI TestClient with the catalog-repository dependency overridden
to point at the `sample_catalog_path` fixture."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api.v1.catalog import get_catalog_repository
from control_plane.catalog import CatalogRepository
from control_plane.main import create_app


def _client(catalog_path: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_catalog_repository] = lambda: CatalogRepository(catalog_path)
    return TestClient(app)


def test_list_catalog_entries(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 7
    assert {row["classification"]["column"] for row in body} >= {"ssn", "test_name"}


def test_list_catalog_entries_filtered_by_category(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog", params={"category": "direct_identifier"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["classification"]["column"] == "ssn"
    assert body[0]["classification"]["tier"] == "direct_identifier"
    assert body[0]["masking_requirement"] == "deterministic_tokenization"


def test_list_catalog_entries_filtered_by_needs_review(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog", params={"needs_review": "true"})
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["classification"]["column"] == "adjustment_reason_code"


def test_catalog_summary(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog/summary")
    assert response.status_code == 200
    body = response.json()
    assert body["total_columns"] == 7
    assert body["needs_review"] == 1


def test_catalog_datasets(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog/datasets")
    assert response.status_code == 200
    body = response.json()
    provider = next(row for row in body if row["dataset"] == "provider")
    assert provider["column_count"] == 2
    assert provider["most_severe_category"] == "pii"


def test_get_single_catalog_entry_found(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog/postgres_enrollment/member/ssn")
    assert response.status_code == 200
    body = response.json()
    assert body["owner"] == "Enrollment Data Engineering"
    assert body["retention_classification"] == "extended"


def test_get_single_catalog_entry_not_found(sample_catalog_path: Path) -> None:
    client = _client(sample_catalog_path)
    response = client.get("/api/v1/catalog/postgres_enrollment/member/does_not_exist")
    assert response.status_code == 404


def test_catalog_not_available_returns_503(tmp_path: Path) -> None:
    client = _client(tmp_path / "missing-catalog.json")
    response = client.get("/api/v1/catalog")
    assert response.status_code == 503
    assert "discovery.cli" in response.json()["detail"]
