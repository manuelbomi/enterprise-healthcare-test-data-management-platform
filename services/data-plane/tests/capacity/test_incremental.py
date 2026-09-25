"""Tests for `data_plane.capacity.incremental.estimate_incremental_savings`
-- real arithmetic over `healthcare_tdm_contracts.DatasetVersion` row
counts (no filesystem/estate dependency; this module models a capability
this repository does not build, per its own docstring)."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from healthcare_tdm_contracts import DatasetVersion

from data_plane.capacity.incremental import estimate_incremental_savings


def _version(*, dataset_name: str, version_number: int, row_counts: dict[str, int]) -> DatasetVersion:
    return DatasetVersion(
        dataset_name=dataset_name,
        version_number=version_number,
        certification_report_id=uuid4(),
        masking_policy_name="phase3-default",
        masking_policy_version=1,
        masking_engine_version="1.0.0",
        storage_uri=f"data/tmp/{dataset_name}/v{version_number}",
        size_bytes=1_000,
        row_counts=row_counts,
        created_by="test",
        created_at=datetime.now(timezone.utc),
    )


def test_estimate_incremental_savings_with_mostly_unchanged_rows() -> None:
    previous = _version(
        dataset_name="claims", version_number=1, row_counts={"member": 100, "claim": 400}
    )
    current = _version(
        dataset_name="claims", version_number=2, row_counts={"member": 105, "claim": 420}
    )

    estimate = estimate_incremental_savings(previous, current)

    assert estimate.previous_total_row_count == 500
    assert estimate.current_total_row_count == 525
    assert estimate.row_count_delta_by_entity == {"member": 5, "claim": 20}
    # unchanged floor = min(100,105) + min(400,420) = 100 + 400 = 500
    assert estimate.unchanged_row_estimate == 500
    assert estimate.full_reprocess_row_count == 525
    assert estimate.estimated_incremental_row_count == 25
    assert estimate.estimated_savings_pct == pytest.approx(1 - 25 / 525)
    assert estimate.estimated_savings_pct > 0.9  # a realistic incremental win, not fabricated


def test_estimate_incremental_savings_with_a_shrinking_entity() -> None:
    previous = _version(dataset_name="claims", version_number=1, row_counts={"member": 100})
    current = _version(dataset_name="claims", version_number=2, row_counts={"member": 60})

    estimate = estimate_incremental_savings(previous, current)
    assert estimate.row_count_delta_by_entity == {"member": -40}
    assert estimate.unchanged_row_estimate == 60
    assert estimate.full_reprocess_row_count == 60
    assert estimate.estimated_incremental_row_count == 0
    assert estimate.estimated_savings_pct == 1.0


def test_estimate_incremental_savings_rejects_different_datasets() -> None:
    previous = _version(dataset_name="claims", version_number=1, row_counts={"member": 10})
    current = _version(dataset_name="labs", version_number=2, row_counts={"member": 10})
    with pytest.raises(ValueError, match="different datasets"):
        estimate_incremental_savings(previous, current)


def test_estimate_incremental_savings_rejects_out_of_order_versions() -> None:
    v1 = _version(dataset_name="claims", version_number=1, row_counts={"member": 10})
    v2 = _version(dataset_name="claims", version_number=2, row_counts={"member": 12})
    with pytest.raises(ValueError, match="version_number"):
        estimate_incremental_savings(v2, v1)


def test_estimate_incremental_savings_zero_rows_has_zero_pct_savings() -> None:
    previous = _version(dataset_name="claims", version_number=1, row_counts={})
    current = _version(dataset_name="claims", version_number=2, row_counts={})
    estimate = estimate_incremental_savings(previous, current)
    assert estimate.full_reprocess_row_count == 0
    assert estimate.estimated_savings_pct == 0.0
