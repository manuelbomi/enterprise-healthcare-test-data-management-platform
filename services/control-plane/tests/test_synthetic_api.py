"""Tests for the synthetic scenario generation manifest read API
(`api/v1/synthetic.py`), exercised through a real FastAPI TestClient with
the repository dependency overridden to point at a temporary artifact
root -- same pattern as `test_catalog_api.py`."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from healthcare_tdm_contracts import (
    DataProvenance,
    ScenarioGenerationRecord,
    ScenarioType,
    SyntheticGenerationManifest,
)

from control_plane.api.v1.synthetic import get_synthetic_manifest_repository
from control_plane.artifacts import SyntheticManifestRepository
from control_plane.main import create_app


def make_manifest() -> SyntheticGenerationManifest:
    return SyntheticGenerationManifest(
        mode="augment",
        base_estate_dir="data/tmp/synthetic-estate-subset",
        seed=90000,
        scenarios=[
            ScenarioGenerationRecord(
                scenario=ScenarioType.HIGH_COST_CLAIMS,
                provenance=DataProvenance.SYNTHETIC,
                description="High-cost claims.",
                row_counts={"Claim": 5},
                anchor_ids=["SYN-MBR-SCEN-000001"],
            ),
        ],
        total_row_counts={"Claim": 5},
        provenance_row_counts={"synthetic": 5, "masked_production_like": 54},
    )


def _client(root: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_synthetic_manifest_repository] = lambda: SyntheticManifestRepository(root)
    return TestClient(app)


def test_list_synthetic_manifests(tmp_path: Path) -> None:
    manifest = make_manifest()
    run_dir = tmp_path / "final"
    run_dir.mkdir()
    (run_dir / "synthetic_generation_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/synthetic/manifests")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["manifest"]["mode"] == "augment"
    assert body[0]["manifest"]["provenance_row_counts"]["synthetic"] == 5


def test_get_synthetic_manifest_by_id(tmp_path: Path) -> None:
    manifest = make_manifest()
    run_dir = tmp_path / "final"
    run_dir.mkdir()
    (run_dir / "synthetic_generation_manifest.json").write_text(manifest.model_dump_json(), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get(f"/api/v1/synthetic/manifests/{manifest.manifest_id}")
    assert response.status_code == 200
    assert response.json()["manifest"]["manifest_id"] == str(manifest.manifest_id)


def test_synthetic_manifests_not_available_returns_503(tmp_path: Path) -> None:
    client = _client(tmp_path / "does-not-exist")
    response = client.get("/api/v1/synthetic/manifests")
    assert response.status_code == 503
    assert "synthetic.cli" in response.json()["detail"]
