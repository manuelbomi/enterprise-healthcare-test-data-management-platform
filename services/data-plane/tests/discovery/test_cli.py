"""Tests for the discovery CLI: real end-to-end run against a real
generated estate, plus the error paths for a missing/empty estate dir.
"""

from __future__ import annotations

import json

import pytest

from data_plane.discovery.cli import main
from data_plane.reference_data.cli import main as reference_data_main


@pytest.fixture(scope="module")
def generated_estate_dir(tmp_path_factory: pytest.TempPathFactory) -> str:
    out_dir = tmp_path_factory.mktemp("cli-estate")
    exit_code = reference_data_main(["--scale", "tiny", "--out-dir", str(out_dir)])
    assert exit_code == 0
    return str(out_dir)


def test_cli_writes_catalog_json(generated_estate_dir: str, tmp_path) -> None:
    out_path = tmp_path / "catalog.json"
    exit_code = main(["--estate-dir", generated_estate_dir, "--out", str(out_path)])
    assert exit_code == 0
    assert out_path.exists()

    rows = json.loads(out_path.read_text(encoding="utf-8"))
    assert len(rows) > 100  # the real tiny estate has 141 columns as of this writing
    assert all("classification" in row for row in rows)


def test_cli_defaults_output_path_to_estate_dir(generated_estate_dir: str) -> None:
    exit_code = main(["--estate-dir", generated_estate_dir])
    assert exit_code == 0
    from pathlib import Path

    assert (Path(generated_estate_dir) / "catalog.json").exists()


def test_cli_fails_cleanly_on_missing_estate_dir(tmp_path) -> None:
    missing = tmp_path / "does-not-exist"
    exit_code = main(["--estate-dir", str(missing)])
    assert exit_code == 1


def test_cli_fails_cleanly_on_empty_estate_dir(tmp_path) -> None:
    empty = tmp_path / "empty-estate"
    empty.mkdir()
    exit_code = main(["--estate-dir", str(empty)])
    assert exit_code == 1
