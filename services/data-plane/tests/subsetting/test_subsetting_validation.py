"""Tests for `data_plane.subsetting.validation`'s three-way integrity
verdict, using hand-built `DanglingReference` findings (so each branch of
the verdict logic -- clean pass, known-orphan pass, and a genuine engine
bug -- is tested directly and deterministically, independent of what the
real estate happens to contain at any given seed)."""

from __future__ import annotations

from healthcare_tdm_contracts import IntegrityStatus

from data_plane.subsetting.closure import ClosureResult, DanglingReference
from data_plane.subsetting.estate_io import RawEstate
from data_plane.subsetting.validation import validate_subset


def _closure(dangling: list[DanglingReference]) -> ClosureResult:
    return ClosureResult(selected=RawEstate(), edges=[], dangling=dangling)


def test_no_findings_at_all_is_a_clean_pass() -> None:
    report = validate_subset(_closure([]))
    assert report.status is IntegrityStatus.PASSED
    assert report.passed is True
    assert report.known_orphan_counts == {}
    assert report.injected_negative_test_orphan_counts == {}
    assert report.engine_bug_counts == {}


def test_source_orphan_only_downgrades_to_passed_with_known_orphans() -> None:
    findings = [DanglingReference(relationship="claim.provider_id", missing_id="SYN-PRV-99999", category="source_orphan")]
    report = validate_subset(_closure(findings))
    assert report.status is IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS
    assert report.passed is True
    assert report.known_orphan_counts == {"claim.provider_id": 1}


def test_engine_bug_fails_regardless_of_other_findings() -> None:
    findings = [
        DanglingReference(relationship="claim.provider_id", missing_id="SYN-PRV-99999", category="source_orphan"),
        DanglingReference(relationship="coverage.plan_id", missing_id="SYN-PLN-0099", category="engine_bug"),
    ]
    report = validate_subset(_closure(findings))
    assert report.status is IntegrityStatus.FAILED
    assert report.passed is False
    assert report.engine_bug_counts == {"coverage.plan_id": 1}


def test_negative_test_injection_is_reported_separately_from_source_orphans() -> None:
    findings = [DanglingReference(relationship="claim.provider_id", missing_id="SYN-PRV-99999", category="source_orphan")]
    injected = [
        DanglingReference(relationship="claim.provider_id", missing_id="SYN-PRV-00042", category="negative_test_injection")
    ]
    report = validate_subset(_closure(findings), negative_test_dangling=injected)
    assert report.status is IntegrityStatus.PASSED_WITH_KNOWN_ORPHANS
    assert report.known_orphan_counts == {"claim.provider_id": 1}
    assert report.injected_negative_test_orphan_counts == {"claim.provider_id": 1}


def test_findings_lines_cover_every_checked_relationship() -> None:
    report = validate_subset(_closure([]))
    # 8 relationships checked by closure.py, one "OK ... 0 dangling" line
    # each, when nothing was found.
    assert len(report.findings) == 8
    assert all(line.startswith("OK") for line in report.findings)


def test_findings_lines_flag_engine_bugs_distinctly() -> None:
    findings = [DanglingReference(relationship="coverage.plan_id", missing_id="X", category="engine_bug")]
    report = validate_subset(_closure(findings))
    fail_lines = [line for line in report.findings if line.startswith("FAIL")]
    assert len(fail_lines) == 1
    assert "coverage.plan_id" in fail_lines[0]
