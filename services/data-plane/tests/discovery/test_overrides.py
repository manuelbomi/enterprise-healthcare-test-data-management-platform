"""Tests for manual-override loading."""

from __future__ import annotations

from pathlib import Path

import pytest

from data_plane.discovery.overrides import DEFAULT_OVERRIDES_PATH, load_overrides


def test_default_overrides_file_loads_the_two_worked_examples() -> None:
    overrides = load_overrides()
    assert ("postgres_enrollment", "provider", "specialty") in overrides
    assert ("object_storage_claims_parquet", "claim", "adjustment_reason_code") in overrides

    raised = overrides[("postgres_enrollment", "provider", "specialty")]
    assert raised.category.value == "sensitive"
    assert raised.confirmed_by

    lowered = overrides[("object_storage_claims_parquet", "claim", "adjustment_reason_code")]
    assert lowered.category.value == "non_sensitive"
    assert lowered.confirmed_by


def test_default_overrides_path_exists_on_disk() -> None:
    assert DEFAULT_OVERRIDES_PATH.exists()


def test_missing_overrides_file_returns_empty_dict(tmp_path: Path) -> None:
    assert load_overrides(tmp_path / "does-not-exist.yaml") == {}


def test_custom_overrides_file_round_trips(tmp_path: Path) -> None:
    custom = tmp_path / "custom_overrides.yaml"
    custom.write_text(
        """
overrides:
  - source_system: postgres_enrollment
    dataset: member
    column: gender
    category: non_sensitive
    reason: "Test override."
    confirmed_by: test.steward
""",
        encoding="utf-8",
    )
    overrides = load_overrides(custom)
    assert len(overrides) == 1
    override = overrides[("postgres_enrollment", "member", "gender")]
    assert override.category.value == "non_sensitive"
    assert override.confirmed_by == "test.steward"


def test_empty_overrides_file_returns_empty_dict(tmp_path: Path) -> None:
    empty = tmp_path / "empty.yaml"
    empty.write_text("", encoding="utf-8")
    assert load_overrides(empty) == {}


@pytest.mark.parametrize("bad_key", ["source_system", "dataset", "column", "category", "reason", "confirmed_by"])
def test_malformed_override_entry_raises(tmp_path: Path, bad_key: str) -> None:
    entry = {
        "source_system": "postgres_enrollment",
        "dataset": "member",
        "column": "gender",
        "category": "non_sensitive",
        "reason": "x",
        "confirmed_by": "y",
    }
    del entry[bad_key]
    import yaml

    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text(yaml.safe_dump({"overrides": [entry]}), encoding="utf-8")
    with pytest.raises(KeyError):
        load_overrides(bad_file)
