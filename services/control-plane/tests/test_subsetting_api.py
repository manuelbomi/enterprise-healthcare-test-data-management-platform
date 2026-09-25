"""Tests for the subsetting manifest read API (`api/v1/subsetting.py`),
exercised through a real FastAPI TestClient with the repository
dependency overridden to point at a temporary artifact root -- same
pattern as `test_catalog_api.py`."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from healthcare_tdm_contracts import (
    IntegrityStatus,
    SubsetManifest,
    SubsetSelectionCriteria,
    SubsettingStrategy,
)

from control_plane.api.v1.subsetting import get_subset_manifest_repository
from control_plane.artifacts import SubsetManifestRepository
from control_plane.main import create_app


def make_manifest() -> SubsetManifest:
    return SubsetManifest(
        scale_profile="tiny",
        selection=SubsetSelectionCriteria(
            strategy=SubsettingStrategy.FIXED_POPULATION,
            parameters={"count": "10"},
            description="Fixed population of 10 members.",
        ),
        source_counts={"Member": 26, "Claim": 140},
        selected_counts={"Member": 10, "Claim": 54},
        integrity_status=IntegrityStatus.PASSED,
    )


def _client(root: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_subset_manifest_repository] = lambda: SubsetManifestRepository(root)
    return TestClient(app)


def test_list_subset_manifests(tmp_path: Path) -> None:
    manifest = make_manifest()
    run_dir = tmp_path / "subset"
    run_dir.mkdir()
    (run_dir / "subset_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/subsetting/manifests")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["manifest"]["selected_counts"]["Member"] == 10
    assert body[0]["manifest"]["integrity_status"] == "passed"


def test_get_subset_manifest_by_id(tmp_path: Path) -> None:
    manifest = make_manifest()
    run_dir = tmp_path / "subset"
    run_dir.mkdir()
    (run_dir / "subset_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get(f"/api/v1/subsetting/manifests/{manifest.manifest_id}")
    assert response.status_code == 200
    assert response.json()["manifest"]["manifest_id"] == str(manifest.manifest_id)


def test_get_subset_manifest_not_found(tmp_path: Path) -> None:
    run_dir = tmp_path / "subset"
    run_dir.mkdir()
    (run_dir / "subset_manifest.json").write_text(make_manifest().model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/subsetting/manifests/00000000-0000-0000-0000-000000000000")
    assert response.status_code == 404


def test_subset_manifests_not_available_returns_503(tmp_path: Path) -> None:
    client = _client(tmp_path / "does-not-exist")
    response = client.get("/api/v1/subsetting/manifests")
    assert response.status_code == 503
    assert "subsetting.cli" in response.json()["detail"]
