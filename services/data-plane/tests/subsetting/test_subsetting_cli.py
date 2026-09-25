"""Tests for `python -m data_plane.subsetting.cli`."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.subsetting.cli import main


def test_nonexistent_estate_dir_fails_cleanly(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--estate-dir",
            str(tmp_path / "nope"),
            "--out-dir",
            str(tmp_path / "out"),
            "--strategy",
            "fixed_population",
            "--param",
            "count=5",
        ]
    )
    assert exit_code == 1


def test_malformed_param_fails_cleanly(real_estate: Path, tmp_path: Path) -> None:
    exit_code = main(
        [
            "--estate-dir",
            str(real_estate),
            "--out-dir",
            str(tmp_path / "out"),
            "--strategy",
            "fixed_population",
            "--param",
            "not-a-key-value-pair",
        ]
    )
    assert exit_code == 1


def test_missing_required_strategy_parameter_fails_cleanly(real_estate: Path, tmp_path: Path) -> None:
    exit_code = main(
        [
            "--estate-dir",
            str(real_estate),
            "--out-dir",
            str(tmp_path / "out"),
            "--strategy",
            "fixed_population",
        ]
    )
    assert exit_code == 1


def test_end_to_end_cli_run_against_a_real_tiny_estate(
    real_estate: Path, tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    out_dir = tmp_path / "subset"
    exit_code = main(
        [
            "--estate-dir",
            str(real_estate),
            "--out-dir",
            str(out_dir),
            "--strategy",
            "fixed_population",
            "--param",
            "count=6",
        ]
    )
    assert exit_code == 0

    captured = capsys.readouterr()
    assert "Integrity status:" in captured.out
    assert (out_dir / "subset_manifest.json").exists()


def test_negative_test_flag_still_exits_zero(real_estate: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "subset-neg"
    exit_code = main(
        [
            "--estate-dir",
            str(real_estate),
            "--out-dir",
            str(out_dir),
            "--strategy",
            "fixed_population",
            "--param",
            "count=20",
            "--negative-test",
        ]
    )
    # A negative-test injection is a "known" orphan category, never FAILED
    # (exit code 2), so the run must still exit 0.
    assert exit_code == 0
