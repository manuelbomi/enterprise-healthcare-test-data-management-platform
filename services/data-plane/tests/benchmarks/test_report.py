"""End-to-end test of `run_full_suite`/`write_report` against a real
`tiny`-scale estate -- proves the whole Phase 14 benchmark pipeline
(generation -> pandas masking/validation -> pandas subsetting -> Spark
masking -> Spark subsetting -> storage footprint) runs start to finish
and produces a real, parseable report, without needing a running Spark
session fixture of its own (`run_full_suite` builds and tears down its
own session internally).
"""

from __future__ import annotations

import json
from pathlib import Path

from data_plane.benchmarks.report import run_full_suite, write_report

TEST_KEY = b"benchmarks-report-test-hmac-key-0123456789"


def test_run_full_suite_produces_every_expected_result(tmp_path: Path) -> None:
    report = run_full_suite(
        "tiny",
        tmp_path / "work",
        seed=20240101,
        member_fraction_pct=50.0,  # tiny scale has only 25 members
        key=TEST_KEY,
    )

    names = {r.name for r in report.results}
    assert any(n.startswith("dataset_generation") for n in names)
    assert any(n.startswith("storage_footprint") for n in names)
    assert any(n.startswith("pandas_masking") for n in names)
    assert "pandas_masking_validation" in names
    assert any(n.startswith("pandas_subsetting") for n in names)
    assert any(n.startswith("spark_masking") for n in names)
    assert any(n.startswith("spark_subsetting") for n in names)

    for result in report.results:
        assert result.elapsed_seconds >= 0
        assert result.rows >= 0

    assert report.environment["spark_master"].startswith("local[*]")
    assert report.environment["scale_profile"] == "tiny"
    assert report.notes  # honesty notes about local[*] must be present


def test_report_markdown_and_json_round_trip(tmp_path: Path) -> None:
    report = run_full_suite(
        "tiny",
        tmp_path / "work",
        seed=20240101,
        member_fraction_pct=50.0,
        key=TEST_KEY,
    )

    markdown = report.to_markdown()
    assert "| Operation | Rows | Elapsed (s) | Records/sec | Notes |" in markdown
    assert "dataset_generation" in markdown

    json_path = tmp_path / "out" / "benchmark_report.json"
    markdown_path = tmp_path / "out" / "benchmark_report.md"
    write_report(report, json_path=json_path, markdown_path=markdown_path)

    assert json_path.exists()
    assert markdown_path.exists()

    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["scale_profile"] == "tiny"
    assert len(payload["results"]) == len(report.results)
    assert payload["results"][0]["records_per_second"] >= 0
