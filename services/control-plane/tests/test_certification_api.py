"""Tests for the certification report read API (`api/v1/certification.py`),
exercised through a real FastAPI TestClient with the repository
dependency overridden to point at a temporary artifact root -- same
pattern as `test_catalog_api.py`. Reuses `conftest.make_certified_report`
so this fixture stays consistent with `test_lifecycle_api.py`'s own
certification report fixture."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api.v1.certification import get_certification_report_repository
from control_plane.artifacts import CertificationReportRepository
from control_plane.main import create_app


def _client(root: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_certification_report_repository] = lambda: CertificationReportRepository(root)
    return TestClient(app)


def test_list_certification_reports(tmp_path: Path, sample_certification_report) -> None:
    report = sample_certification_report
    (tmp_path / "certification_report.json").write_text(report.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/certification/reports")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["report"]["status"] == "certified"
    assert body[0]["report"]["dataset_name"] == "tiny-fixed_population"


def test_get_certification_report_by_id(tmp_path: Path, sample_certification_report) -> None:
    report = sample_certification_report
    (tmp_path / "certification_report.json").write_text(report.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get(f"/api/v1/certification/reports/{report.report_id}")
    assert response.status_code == 200
    assert response.json()["report"]["report_id"] == str(report.report_id)


def test_get_certification_report_not_found(tmp_path: Path, sample_certification_report) -> None:
    report = sample_certification_report
    (tmp_path / "certification_report.json").write_text(report.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/certification/reports/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_certification_reports_not_available_returns_503(tmp_path: Path) -> None:
    client = _client(tmp_path / "does-not-exist")
    response = client.get("/api/v1/certification/reports")
    assert response.status_code == 503
    assert "certification.cli" in response.json()["detail"]
