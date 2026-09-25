"""`python -m data_plane.synthetic.cli`: argument parsing and end-to-end
behavior in both modes."""

from __future__ import annotations

from pathlib import Path

from data_plane.synthetic.cli import main


def test_cli_standalone_mode_with_all_scenarios(tmp_path: Path, capsys: object) -> None:
    out_dir = tmp_path / "out"
    exit_code = main(["--out-dir", str(out_dir), "--all-scenarios", "--seed", "5"])
    assert exit_code == 0
    assert (out_dir / "synthetic_generation_manifest.json").exists()


def test_cli_augment_mode(subset_estate: Path, tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    exit_code = main(
        [
            "--base-estate-dir",
            str(subset_estate),
            "--out-dir",
            str(out_dir),
            "--scenario",
            "high_cost_claims",
            "--scenario",
            "missing_provider",
        ]
    )
    assert exit_code == 0
    assert (out_dir / "synthetic_generation_manifest.json").exists()
    assert (out_dir / "postgres_enrollment" / "enrollment.sqlite3").exists()


def test_cli_requires_at_least_one_scenario(tmp_path: Path) -> None:
    exit_code = main(["--out-dir", str(tmp_path / "out")])
    assert exit_code == 1


def test_cli_rejects_nonexistent_base_estate_dir(tmp_path: Path) -> None:
    exit_code = main(
        [
            "--base-estate-dir",
            str(tmp_path / "does-not-exist"),
            "--out-dir",
            str(tmp_path / "out"),
            "--scenario",
            "normal_claims",
        ]
    )
    assert exit_code == 1


def test_cli_rejects_malformed_count_flag(tmp_path: Path) -> None:
    exit_code = main(
        ["--out-dir", str(tmp_path / "out"), "--scenario", "normal_claims", "--count", "not-valid"]
    )
    assert exit_code == 1


def test_cli_honors_count_override(tmp_path: Path) -> None:
    out_dir = tmp_path / "out"
    exit_code = main(
        [
            "--out-dir",
            str(out_dir),
            "--scenario",
            "high_cost_claims",
            "--count",
            "high_cost_claims=6",
            "--seed",
            "1",
        ]
    )
    assert exit_code == 0
    import json

    manifest = json.loads((out_dir / "synthetic_generation_manifest.json").read_text(encoding="utf-8"))
    record = next(s for s in manifest["scenarios"] if s["scenario"] == "high_cost_claims")
    assert record["row_counts"]["claim"] == 6
