"""Real, executed proof for `problems_final_review.md` P2-3 ("retention
sweep and vacuum-candidate identification have no automatic trigger"):
`scripts/run_scheduled_maintenance.py` is a real, runnable entry point
that runs the due-refresh sweep, the retention sweep, and
vacuum-candidate identification in one call -- exactly what a cron
entry, a Kubernetes `CronJob`, or an Airflow task would invoke on a
schedule (see that script's own module docstring for why no
cron/Kubernetes manifest is shipped alongside it).

`scripts/` is not an installed package (no `pyproject.toml`, deliberately
-- these are one-off operator scripts, same as `demo_phase7_lifecycle.py`
etc.), so this test loads it directly from its file path rather than
`import`ing it as a module.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import ModuleType
from uuid import UUID

import pytest
from healthcare_tdm_contracts import DatasetVersionStatus, Environment, RefreshTrigger

from control_plane.db.models import create_sqlite_engine
from control_plane.db.session import build_session_factory
from control_plane.domain.lifecycle.repository import LifecycleRepository

from conftest import make_certified_report

SCRIPT_PATH = Path(__file__).resolve().parents[3] / "scripts" / "run_scheduled_maintenance.py"


def _load_script() -> ModuleType:
    spec = importlib.util.spec_from_file_location("run_scheduled_maintenance", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    # Register before exec: `MaintenanceRunSummary`'s `from __future__
    # import annotations` dataclass fields are resolved by looking the
    # module up in `sys.modules` by name -- without this, that lookup
    # fails since the module isn't registered under its own name yet.
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def maintenance_script() -> ModuleType:
    return _load_script()


def _seed_due_refresh_and_expired_version(repository: LifecycleRepository) -> tuple[str, str]:
    """Register two dataset versions and one environment request: the
    older version is given the minimum allowed `retention_days=1`
    (expires almost immediately -- due for `apply_retention` once
    `run_maintenance` is called with `as_of` a day or more later) and,
    once the request is repointed at the newer version below, is left
    unreferenced (a vacuum candidate once expired)."""

    old_version = repository.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(dataset_name="ds"),
        storage_uri="data/tmp/old",
        size_bytes=100,
        row_counts={"member": 1},
        created_by="steward@example.org",
        retention_days=1,  # expires almost immediately -- the minimum allowed
    )
    request = repository.request_environment(
        environment=Environment.DEV, dataset_name="ds", requested_by="a"
    )
    # A newer version supersedes the one the request currently points
    # at, so a refresh moves the request onto it and leaves the older
    # version unreferenced.
    repository.register_dataset_version(
        dataset_name="ds",
        certification_report=make_certified_report(dataset_name="ds"),
        storage_uri="data/tmp/new",
        size_bytes=200,
        row_counts={"member": 2},
        created_by="steward@example.org",
    )
    repository.refresh(request.request_id, trigger=RefreshTrigger.ON_DEMAND, triggered_by="a")
    return str(old_version.version_id), str(request.request_id)


def test_run_maintenance_sweeps_refreshes_expires_retention_and_finds_vacuum_candidates(
    tmp_path: Path, maintenance_script: ModuleType
) -> None:
    engine = create_sqlite_engine(str(tmp_path / "maintenance.db"))
    factory = build_session_factory(engine)
    session = factory()
    repository = LifecycleRepository(session)

    old_version_id, request_id = _seed_due_refresh_and_expired_version(repository)
    session.commit()

    # `retention_days=1` above means `expires_at` is one day after
    # registration -- comfortably in the past relative to `far_future`.
    far_future = datetime.now(timezone.utc) + timedelta(days=30)
    summary = maintenance_script.run_maintenance(session, as_of=far_future)
    session.commit()

    assert summary.skipped_due_to_lock is False
    assert old_version_id in summary.retention_expired_version_ids

    version = repository.get_version(UUID(old_version_id))
    assert version.status == DatasetVersionStatus.EXPIRED

    # Now unreferenced (nothing points at it) and EXPIRED -> a real
    # vacuum candidate.
    assert old_version_id in summary.vacuum_candidate_version_ids
    assert summary.vacuum_candidate_reclaimable_bytes >= 100

    session.close()


def test_run_maintenance_reports_skipped_when_the_sweep_lock_is_already_held(tmp_path: Path, maintenance_script: ModuleType) -> None:
    from control_plane.db.models import SchedulerLockRow
    from control_plane.platform.scheduler_lock import LIFECYCLE_SCHEDULER_SWEEP_LOCK

    engine = create_sqlite_engine(str(tmp_path / "maintenance_locked.db"))
    factory = build_session_factory(engine)
    holder_session = factory()
    holder_session.add(
        SchedulerLockRow(
            lock_name=LIFECYCLE_SCHEDULER_SWEEP_LOCK,
            acquired_by="another-run-in-progress",
            acquired_at=datetime.now(timezone.utc),
        )
    )
    holder_session.commit()

    caller_session = factory()
    summary = maintenance_script.run_maintenance(caller_session)
    assert summary.skipped_due_to_lock is True
    assert summary.refresh_attempted == 0

    holder_session.close()
    caller_session.close()


def test_main_prints_a_json_summary_and_exits_zero(tmp_path: Path, maintenance_script: ModuleType, capsys: pytest.CaptureFixture[str]) -> None:
    db_path = tmp_path / "main.db"
    exit_code = maintenance_script.main(["--database-url", f"sqlite:///{db_path}"])
    assert exit_code == 0

    captured = capsys.readouterr()
    payload = json.loads(captured.out)
    assert payload["refresh_attempted"] == 0
    assert payload["skipped_due_to_lock"] is False
