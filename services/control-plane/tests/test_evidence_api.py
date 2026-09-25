"""Tests for the Audit Evidence Package API (`api/v1/evidence.py`),
exercised through a real FastAPI `TestClient`, mirroring
`test_lifecycle_api.py`'s dependency-override pattern -- and, since
`get_evidence_repository` also depends on `Settings.catalog_path`, the
`TDM_CONTROL_PLANE_CATALOG_PATH` override `test_catalog_api.py` uses.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.config import Settings, get_settings
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app

from conftest import SAMPLE_ENTRIES, make_certified_report


def _client(db_path: Path, catalog_path: Path) -> TestClient:
    engine = create_sqlite_engine(str(db_path))
    factory = build_session_factory(engine)

    def _override_session() -> Iterator[Session]:
        with session_scope(factory) as session:
            yield session

    def _override_settings() -> Settings:
        return Settings(catalog_path=str(catalog_path))

    app = create_app()
    app.dependency_overrides[get_db_session] = _override_session
    app.dependency_overrides[get_settings] = _override_settings
    return TestClient(app)


@pytest.fixture
def catalog_path(tmp_path: Path) -> Path:
    path = tmp_path / "catalog.json"
    payload = [json.loads(entry.model_dump_json()) for entry in SAMPLE_ENTRIES]
    path.write_text(json.dumps(payload), encoding="utf-8")
    return path


@pytest.fixture
def client(tmp_path: Path, catalog_path: Path) -> TestClient:
    return _client(tmp_path / "evidence.db", catalog_path)


def _register_version(client: TestClient, dataset_name: str = "member") -> dict:
    report = make_certified_report(dataset_name=dataset_name)
    response = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": dataset_name,
            "certification_report": json.loads(report.model_dump_json()),
            "storage_uri": "s3://tdm-bucket/member/v1",
            "size_bytes": 1_000,
            "row_counts": {"member": 26},
            "created_by": "pipeline@example.org",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_generate_evidence_package_over_http(client: TestClient) -> None:
    version = _register_version(client)

    response = client.post(
        f"/api/v1/evidence/dataset-versions/{version['version_id']}/package",
        json={"generated_by": "auditor@example.org"},
    )
    assert response.status_code == 201, response.text
    package = response.json()

    assert package["dataset_version_id"] == version["version_id"]
    assert package["dataset_name"] == "member"
    assert package["bundle_checksum"]
    assert package["classification_summary"]["column_count"] == 2  # ssn + date_of_birth
    assert "certification" in package["compliance_disclaimer"].lower() or "compliance" in package["compliance_disclaimer"].lower()
    assert any("No CertificationReport was supplied" in n for n in package["provenance_notes"])

    # generating the package itself produced a real audit event
    events = client.get(
        "/api/v1/audit/events",
        params={"event_type": "evidence_package_generated", "subject": version["version_id"]},
    ).json()
    assert len(events) == 1
    assert events[0]["actor"] == "auditor@example.org"


def test_generate_evidence_package_embeds_supplied_certification_report(client: TestClient) -> None:
    version = _register_version(client)
    report = make_certified_report(dataset_name="member")

    response = client.post(
        f"/api/v1/evidence/dataset-versions/{version['version_id']}/package",
        json={
            "generated_by": "auditor@example.org",
            "certification_report": json.loads(report.model_dump_json()),
        },
    )
    assert response.status_code == 201, response.text
    package = response.json()

    assert package["certification_report"] is not None
    assert package["certification_report"]["report_id"] == str(report.report_id)
    assert "referential_integrity" in package["integrity_report"]


def test_generate_evidence_package_for_missing_version_returns_404(client: TestClient) -> None:
    response = client.post(
        "/api/v1/evidence/dataset-versions/00000000-0000-0000-0000-000000000000/package",
        json={"generated_by": "auditor@example.org"},
    )
    assert response.status_code == 404
