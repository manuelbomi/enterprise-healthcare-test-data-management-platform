"""Tests for `data_plane.subsetting.manifest`."""

from __future__ import annotations

from pathlib import Path

from data_plane.subsetting.manifest import estimate_storage_bytes


def test_estimate_storage_bytes_of_nonexistent_dir_is_zero(tmp_path: Path) -> None:
    assert estimate_storage_bytes(tmp_path / "does-not-exist") == 0


def test_estimate_storage_bytes_sums_files_recursively(tmp_path: Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "one.txt").write_text("12345", encoding="utf-8")  # 5 bytes
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "two.txt").write_text("1234567890", encoding="utf-8")  # 10 bytes

    assert estimate_storage_bytes(tmp_path) == 15
