"""Tests for `python -m data_plane.certification.cli`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from data_plane.certification import signing as certification_signing
from data_plane.certification.cli import main
from data_plane.masking import secrets as masking_secrets


def test_generate_dev_key_flag_prints_both_keys_and_exits_zero(capsys: pytest.CaptureFixture) -> None:
    exit_code = main(["--generate-dev-key"])
    assert exit_code == 0
    captured = capsys.readouterr()
    assert masking_secrets.ENV_VAR in captured.out
    assert certification_signing.ENV_VAR in captured.out
    assert "LOCAL DEV/TEST-ONLY" in captured.out


def test_missing_out_dir_without_generate_dev_key_fails(capsys: pytest.CaptureFixture) -> None:
    exit_code = main([])
    assert exit_code == 1
    assert "--out-dir" in capsys.readouterr().err


def test_missing_masking_key_fails_cleanly(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.delenv(masking_secrets.ENV_VAR, raising=False)
    monkeypatch.chdir(tmp_path)
    exit_code = main(["--out-dir", str(tmp_path / "run"), "--strategy", "fixed_population", "--param", "count=5"])
    assert exit_code == 1
    assert "--generate-dev-key" in capsys.readouterr().err


def test_end_to_end_cli_run_reaches_certified_and_publishes(
    real_estate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "cli-cert-integration-test-key-01234")
    monkeypatch.setenv(certification_signing.ENV_VAR, "cli-cert-integration-signing-key-98765")

    out_dir = tmp_path / "run"
    exit_code = main(
        [
            "--estate-dir",
            str(real_estate),
            "--out-dir",
            str(out_dir),
            "--strategy",
            "fixed_population",
            "--param",
            "count=8",
            "--publish",
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Status: PUBLISHED" in captured.out
    assert "[PASS]" in captured.out

    report = json.loads((out_dir / "certification_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "published"
    assert len(report["gates"]) == 11
    assert report["integrity_signature"] is not None


def test_cli_run_without_publish_stops_at_certified(
    real_estate: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setenv(masking_secrets.ENV_VAR, "cli-cert-integration-test-key-01234")
    monkeypatch.setenv(certification_signing.ENV_VAR, "cli-cert-integration-signing-key-98765")

    out_dir = tmp_path / "run-no-publish"
    exit_code = main(
        [
            "--estate-dir",
            str(real_estate),
            "--out-dir",
            str(out_dir),
            "--strategy",
            "fixed_population",
            "--param",
            "count=8",
        ]
    )
    assert exit_code == 0
    report = json.loads((out_dir / "certification_report.json").read_text(encoding="utf-8"))
    assert report["status"] == "certified"
    assert report["published_at"] is None
