"""Tests for the masking run read API (`api/v1/masking.py`), exercised
through a real FastAPI TestClient with the repository dependency
overridden to point at a temporary artifact root -- same pattern as
`test_catalog_api.py`."""

from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from control_plane.api.v1.masking import get_masking_run_repository
from control_plane.artifacts import MaskingRunRepository
from control_plane.main import create_app

SAMPLE_SUMMARY = {
    "rows_processed": 120,
    "columns_masked": 340,
    "technique_counts": {"hmac_pseudonymization": 200, "format_preserving_synthetic": 140},
    "files_written": ["member.parquet", "claim.parquet"],
    "warning_count": 0,
    "masking_engine_version": "1.0.0",
    "policy_name": "phase3-default",
    "policy_version": 1,
    "validation_passed": True,
    "validation_checks": ["referential_integrity", "no_raw_value_leakage"],
    "validation_failures": [],
}


def _client(root: Path) -> TestClient:
    app = create_app()
    app.dependency_overrides[get_masking_run_repository] = lambda: MaskingRunRepository(root)
    return TestClient(app)


def test_list_masking_runs(tmp_path: Path) -> None:
    run_dir = tmp_path / "masked"
    run_dir.mkdir()
    (run_dir / "masking_run_summary.json").write_text(json.dumps(SAMPLE_SUMMARY), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/masking/runs")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]["summary"]["rows_processed"] == 120
    assert body[0]["summary"]["technique_counts"]["hmac_pseudonymization"] == 200
    assert body[0]["source_path"].endswith("masking_run_summary.json")


def test_list_masking_runs_discovers_multiple(tmp_path: Path) -> None:
    for name in ("run-a", "run-b"):
        run_dir = tmp_path / name
        run_dir.mkdir()
        (run_dir / "masking_run_summary.json").write_text(json.dumps(SAMPLE_SUMMARY), encoding="utf-8")

    client = _client(tmp_path)
    response = client.get("/api/v1/masking/runs")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_masking_runs_not_available_returns_503(tmp_path: Path) -> None:
    client = _client(tmp_path / "does-not-exist")
    response = client.get("/api/v1/masking/runs")
    assert response.status_code == 503
    assert "masking.cli" in response.json()["detail"]
