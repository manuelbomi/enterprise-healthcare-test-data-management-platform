#!/usr/bin/env python
"""Generate real, on-disk data for the Phase 9 web console to render.

Unlike `demo_phase7_lifecycle.py` (which tears its output down into a
throwaway `tmp_path`-style directory to demonstrate the API in isolation),
this script deliberately writes to the exact paths `control_plane.config.
Settings`'s *defaults* point at, so `uvicorn control_plane.main:app` run
with zero extra environment variables serves this real data -- which is
what the frontend console, and its Playwright tests, are exercised
against. Same plane-separation note as `demo_phase7_lifecycle.py`: this
is a standalone operator script gluing two real services' public
interfaces together, not either service's own source importing the
other (ADR-0003).

Produces:

- Two real Phase 6 certification pipeline runs
  (`data/tmp/phase9-demo/run-v1` with an additional synthetic scenario,
  `data/tmp/phase9-demo/run-v2` without), each with its own
  `catalog.json`, `subset/subset_manifest.json`,
  `masked/masking_run_summary.json`, and `certification_report.json` --
  everything the Phase 9 masking/subsetting/synthetic/certification
  read-only artifact endpoints (`control_plane.artifacts`) discover via
  `TDM_CONTROL_PLANE_{MASKING,SUBSETTING,SYNTHETIC,CERTIFICATION}
  _ARTIFACTS_ROOT` (default `data/tmp`, which covers both run
  directories).
- A copy of run-v2's `catalog.json` at the Phase 2 catalog API's default
  path (`data/tmp/synthetic-estate/catalog.json`), so `GET
  /api/v1/catalog` works with zero configuration too.
- Two registered `DatasetVersion`s and five `EnvironmentDatasetRequest`s
  (DEV/QA/SIT/UAT/PERFORMANCE) in the default lifecycle database
  (`data/tmp/control-plane/lifecycle.db`), including one on-demand
  refresh so the dashboard's "upcoming refreshes" / "environment demand"
  views have more than one data point.

Usage::

    python scripts/demo_phase9_console_data.py
    # then, from services/control-plane:
    uvicorn control_plane.main:app --reload
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from fastapi.testclient import TestClient
from healthcare_tdm_contracts import ScenarioType, SubsettingStrategy

from control_plane.api.v1.lifecycle import get_db_session
from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory, session_scope
from control_plane.main import create_app
from data_plane.certification import signing as certification_signing
from data_plane.certification.pipeline import run_certification_pipeline
from data_plane.masking import secrets as masking_secrets

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "data" / "tmp" / "phase9-demo"
DEFAULT_CATALOG_PATH = REPO_ROOT / "data" / "tmp" / "synthetic-estate" / "catalog.json"
DEFAULT_LIFECYCLE_DB = REPO_ROOT / "data" / "tmp" / "control-plane" / "lifecycle.db"


def banner(title: str) -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def directory_size_bytes(path: Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def parse_final_row_counts(row_count_reconciliation: dict[str, str]) -> dict[str, int]:
    import re

    counts: dict[str, int] = {}
    for entity, trail in row_count_reconciliation.items():
        match = re.search(r"final=(\d+)", trail)
        if match:
            counts[entity] = int(match.group(1))
    return counts


def build_client(db_path: Path) -> TestClient:
    engine = create_sqlite_engine(str(db_path))
    factory = build_session_factory(engine)

    def _override():
        with session_scope(factory) as session:
            yield session

    app = create_app()
    app.dependency_overrides[get_db_session] = _override
    return TestClient(app)


def main() -> int:
    if DEMO_DIR.exists():
        shutil.rmtree(DEMO_DIR)
    DEMO_DIR.mkdir(parents=True, exist_ok=True)
    DEFAULT_LIFECYCLE_DB.parent.mkdir(parents=True, exist_ok=True)
    if DEFAULT_LIFECYCLE_DB.exists():
        DEFAULT_LIFECYCLE_DB.unlink()

    banner("STEP 1 -- Certification pipeline run v1 (with a synthetic scenario)")
    masking_key = masking_secrets.generate_dev_key().encode("utf-8")
    signing_key = certification_signing.generate_dev_key().encode("utf-8")

    run1 = run_certification_pipeline(
        DEMO_DIR / "run-v1",
        scale="tiny",
        seed=20240101,
        subset_strategy=SubsettingStrategy.FIXED_POPULATION,
        subset_parameters={"count": "10"},
        masking_key=masking_key,
        synthetic_scenarios=[ScenarioType.HIGH_COST_CLAIMS, ScenarioType.INVALID_CLAIM_REFERENCES],
        signing_key=signing_key,
        dataset_name="phase9-console-demo",
        actor="phase9-demo-script",
        auto_publish=True,
    )
    report1 = run1.report
    print(f"Certification report 1: {run1.report_path}  status={report1.status.value}")
    assert report1.status.value in ("certified", "published"), report1.model_dump_json(indent=2)
    final_dir_1 = run1.final_dir
    size_1 = directory_size_bytes(final_dir_1)
    row_counts_1 = parse_final_row_counts(report1.row_count_reconciliation)

    banner("STEP 2 -- Certification pipeline run v2 (larger population, no synthetic)")
    run2 = run_certification_pipeline(
        DEMO_DIR / "run-v2",
        scale="tiny",
        seed=20240102,
        subset_strategy=SubsettingStrategy.PERCENTAGE,
        subset_parameters={"percentage": "40"},
        masking_key=masking_key,
        signing_key=signing_key,
        dataset_name="phase9-console-demo",
        actor="phase9-demo-script",
        auto_publish=True,
    )
    report2 = run2.report
    print(f"Certification report 2: {run2.report_path}  status={report2.status.value}")
    assert report2.status.value in ("certified", "published"), report2.model_dump_json(indent=2)
    final_dir_2 = run2.final_dir
    size_2 = directory_size_bytes(final_dir_2)
    row_counts_2 = parse_final_row_counts(report2.row_count_reconciliation)

    banner("STEP 3 -- Copy run-v2's catalog.json to the default catalog API path")
    DEFAULT_CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(run2.catalog_path, DEFAULT_CATALOG_PATH)
    print(f"Wrote {DEFAULT_CATALOG_PATH}")

    banner("STEP 4 -- Register both dataset versions in the default lifecycle database")
    client = build_client(DEFAULT_LIFECYCLE_DB)

    resp = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "phase9-console-demo",
            "certification_report": json.loads(report1.model_dump_json()),
            "storage_uri": str(final_dir_1),
            "size_bytes": size_1,
            "row_counts": row_counts_1,
            "created_by": "phase9-demo-script",
            "notes": "Phase 9 console demo data, run v1 (with synthetic scenarios).",
        },
    )
    assert resp.status_code == 201, resp.text
    version_1 = resp.json()
    print(f"Registered version_id={version_1['version_id']} version_number={version_1['version_number']}")

    resp = client.post(
        "/api/v1/lifecycle/dataset-versions",
        json={
            "dataset_name": "phase9-console-demo",
            "certification_report": json.loads(report2.model_dump_json()),
            "storage_uri": str(final_dir_2),
            "size_bytes": size_2,
            "row_counts": row_counts_2,
            "created_by": "phase9-demo-script",
            "notes": "Phase 9 console demo data, run v2 (larger population).",
        },
    )
    assert resp.status_code == 201, resp.text
    version_2 = resp.json()
    print(f"Registered version_id={version_2['version_id']} version_number={version_2['version_number']}")

    banner("STEP 5 -- Request the dataset into all five environments")
    requests: dict[str, dict] = {}
    for env, consumer in [
        ("dev", "claims-dev-team"),
        ("qa", "claims-qa-team"),
        ("sit", "integration-test-team"),
        ("uat", "release-readiness-team"),
        ("performance", "perf-engineering-team"),
    ]:
        resp = client.post(
            "/api/v1/lifecycle/environment-requests",
            json={
                "environment": env,
                "dataset_name": "phase9-console-demo",
                "requested_by": "phase9-demo-script",
                "consumer": consumer,
            },
        )
        assert resp.status_code == 201, resp.text
        requests[env] = resp.json()
        print(f"  {env:>12}: current_version={requests[env]['current_version_number']}")

    banner("STEP 6 -- Refresh QA onto version 2, leave DEV on version 1")
    resp = client.post(
        f"/api/v1/lifecycle/environment-requests/{requests['qa']['request_id']}/refresh",
        json={"triggered_by": "phase9-demo-script", "trigger": "on_demand"},
    )
    assert resp.status_code == 200, resp.text
    print(f"QA refresh: {resp.json()['detail']}")

    banner("STEP 7 -- Sanity-check the read-only artifact endpoints this script fed")
    for path, label in [
        ("/api/v1/catalog/summary", "catalog"),
        ("/api/v1/masking/runs", "masking"),
        ("/api/v1/subsetting/manifests", "subsetting"),
        ("/api/v1/synthetic/manifests", "synthetic"),
        ("/api/v1/certification/reports", "certification"),
        ("/api/v1/lifecycle/dataset-versions", "lifecycle versions"),
        ("/api/v1/capacity/plan", "capacity plan"),
    ]:
        r = client.get(path)
        count = len(r.json()) if isinstance(r.json(), list) else "n/a"
        print(f"  {label:<20} {path:<38} HTTP {r.status_code}  count={count}")
        assert r.status_code == 200, (path, r.text)

    banner("DONE -- Phase 9 console demo data generated")
    print(f"Demo artifact root: {DEMO_DIR}")
    print(f"Default catalog path: {DEFAULT_CATALOG_PATH}")
    print(f"Default lifecycle DB: {DEFAULT_LIFECYCLE_DB}")
    print("Start the server with default settings: (cd services/control-plane && uvicorn control_plane.main:app --reload)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
