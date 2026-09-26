"""Tests for `python -m data_plane.masking.cli`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_plane.discovery.catalog_builder import build_catalog, write_catalog
from data_plane.discovery.engine import ClassificationEngine
from data_plane.discovery.scanner import scan_estate
from data_plane.masking import secrets as masking_secrets
from data_plane.masking.cli import main
from data_plane.reference_data.edge_cases import DEFAULT_EDGE_CASE_CONFIG
from data_plane.reference_data.estate_writer import write_estate
from data_plane.reference_data.generator import EstateGenerator
from data_plane.reference_data.scale import SCALE_PROFILES


def test_generate_dev_key_flag_prints_a_key_and_exits_zero(capsys: pytest.CaptureFixture) -> None:
    exit_code = main(["--generate-dev-key"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert masking_secrets.ENV_VAR in captured.out
    assert "LOCAL DEV/TEST-ONLY" in captured.out


def test_missing_required_args_without_generate_dev_key_fails(capsys: pytest.CaptureFixture) -> None:
    exit_code = main([])
    assert exit_code == 1


def test_nonexistent_estate_dir_fails_cleanly(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "x" * 32)
    exit_code = main(
        ["--estate-dir", str(tmp_path / "nope"), "--catalog", str(tmp_path / "catalog.json")]
    )
    assert exit_code == 1


def test_missing_key_fails_with_remediation_message(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv(masking_secrets.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)  # no .env here either
    estate_dir = tmp_path / "estate"
    estate_dir.mkdir()
    catalog_path = tmp_path / "catalog.json"
    catalog_path.write_text("[]", encoding="utf-8")

    exit_code = main(["--estate-dir", str(estate_dir), "--catalog", str(catalog_path)])
    assert exit_code == 1
    assert "--generate-dev-key" in capsys.readouterr().err


def test_end_to_end_cli_run_against_a_real_tiny_estate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "cli-integration-test-key-0123456789")

    estate_dir = tmp_path / "estate"
    generator = EstateGenerator(SCALE_PROFILES["tiny"], DEFAULT_EDGE_CASE_CONFIG, seed=99)
    estate = generator.generate()
    write_estate(estate, estate_dir)

    catalog_path = estate_dir / "catalog.json"
    entries = build_catalog(scan_estate(estate_dir), ClassificationEngine())
    write_catalog(entries, catalog_path)

    out_dir = tmp_path / "masked"
    exit_code = main(
        ["--estate-dir", str(estate_dir), "--catalog", str(catalog_path), "--out-dir", str(out_dir)]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Validation: PASSED" in captured.out

    summary = json.loads((out_dir / "masking_run_summary.json").read_text(encoding="utf-8"))
    assert summary["validation_passed"] is True
    assert summary["columns_masked"] > 0
    assert "tokenization" in summary["technique_counts"]

    # Phase 18B (`docs/problems/problems_final_review.md` P3-7): this artifact is now
    # constructed from -- and therefore must validate cleanly against --
    # the shared `healthcare_tdm_contracts.MaskingRunSummary` contract,
    # the same class `control_plane.artifacts.masking` imports to read
    # this exact file back. Real proof the writer and reader agree on
    # one shape, not two independently-maintained ones.
    from healthcare_tdm_contracts import MaskingRunSummary

    parsed = MaskingRunSummary.model_validate(summary)
    assert parsed.validation_passed is True
    assert parsed.columns_masked == summary["columns_masked"]
