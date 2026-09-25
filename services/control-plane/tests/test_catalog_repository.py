"""Tests for `CatalogRepository` against the shared `sample_catalog_path`
fixture (see conftest.py)."""

from __future__ import annotations

from pathlib import Path

import pytest
from healthcare_tdm_contracts import ClassificationTier, SensitivityCategory

from control_plane.catalog import CatalogNotAvailableError, CatalogRepository


def test_missing_catalog_raises_not_available(tmp_path: Path) -> None:
    repo = CatalogRepository(tmp_path / "does-not-exist.json")
    with pytest.raises(CatalogNotAvailableError):
        repo.list_entries()


def test_list_entries_no_filter_returns_everything(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    assert len(repo.list_entries()) == 7


def test_filter_by_source_system(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    results = repo.list_entries(source_system="s3_clinical_data_lake")
    assert len(results) == 1
    assert results[0].column == "test_name"


def test_filter_by_category(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    results = repo.list_entries(category=SensitivityCategory.DIRECT_IDENTIFIER)
    assert {r.column for r in results} == {"ssn"}


def test_filter_by_tier(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    results = repo.list_entries(tier=ClassificationTier.SENSITIVE_CLINICAL_ATTRIBUTE)
    assert {r.column for r in results} == {"test_name", "adjustment_reason_code", "specialty"}


def test_filter_by_needs_review(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    needs_review = repo.list_entries(needs_review=True)
    assert {r.column for r in needs_review} == {"adjustment_reason_code"}

    confirmed_or_confident = repo.list_entries(needs_review=False)
    assert {r.column for r in confirmed_or_confident} == {
        "ssn",
        "date_of_birth",
        "test_name",
        "npi",
        "plan_name",
        "specialty",
    }


def test_combined_filters(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    results = repo.list_entries(source_system="postgres_enrollment", dataset="provider")
    assert {r.column for r in results} == {"npi", "specialty"}


def test_get_entry_found_and_not_found(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    found = repo.get_entry("postgres_enrollment", "member", "ssn")
    assert found is not None
    assert found.classification.category == SensitivityCategory.DIRECT_IDENTIFIER

    assert repo.get_entry("postgres_enrollment", "member", "nope") is None


def test_list_datasets_groups_and_picks_most_severe(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    datasets = {(row["source_system"], row["dataset"]): row for row in repo.list_datasets()}

    provider_row = datasets[("postgres_enrollment", "provider")]
    assert provider_row["column_count"] == 2
    # PII (npi) vs SENSITIVE (specialty) -> PII is more severe per precedence().
    assert provider_row["most_severe_category"] == SensitivityCategory.PII

    member_row = datasets[("postgres_enrollment", "member")]
    assert member_row["column_count"] == 2
    assert member_row["most_severe_category"] == SensitivityCategory.DIRECT_IDENTIFIER


def test_summary_counts(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    summary = repo.summary()
    assert summary["total_columns"] == 7
    assert summary["total_datasets"] == 5
    assert summary["needs_review"] == 1
    assert summary["by_category"]["direct_identifier"] == 1
    assert summary["by_category"]["non_sensitive"] == 1


def test_reload_picks_up_changes(sample_catalog_path: Path) -> None:
    repo = CatalogRepository(sample_catalog_path)
    assert len(repo.list_entries()) == 7

    sample_catalog_path.write_text("[]", encoding="utf-8")
    assert len(repo.list_entries()) == 7  # cached; unchanged until reload()

    repo.reload()
    assert len(repo.list_entries()) == 0
