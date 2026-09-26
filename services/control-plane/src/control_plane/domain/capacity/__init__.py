"""Storage and compute capacity planning (Phase 8) -- the control-plane
half, per `docs/adr/0013-capacity-planning-plane-split.md`. Reads
Phase 7's real `DatasetVersion`/`EnvironmentDatasetRequest` data via
`LifecycleRepository` (never modifies it) and aggregates real footprint/
demand numbers, plus a pure illustrative percentage-of-production
scenario model.

Module map
----------
- `estimator.py` -- pure, dependency-free compute-demand/processing-volume
  heuristics (`estimate_compute_unit_hours`, `estimate_refreshes_per_year`,
  ...). Honestly documented as illustrative, not benchmarked -- see
  `problems_phase_08.md` P8-1.
- `planner.py` -- `CapacityPlanner`, the real, DB-backed service
  (`dataset_version_footprint`, `environment_capacity_demand`,
  `capacity_plan`, `vacuum_candidates`), plus `illustrative_capacity_plan`,
  the pure function implementing `ROADMAP.md` Phase 8's "Production:
  100 TB, QA 10%, SIT 5%, UAT 15%" example as a real, configurable model.
- `scenario_history.py` -- `CapacityScenarioHistoryRepository` (Phase
  18B, `problems_final_review.md` P3-3): real, DB-backed, append-only
  persistence for a saved `IllustrativeCapacityPlan` snapshot, so a
  scenario can be saved and compared against a later one instead of
  every plan being purely stateless.
"""

from control_plane.domain.capacity.planner import CapacityPlanner, illustrative_capacity_plan
from control_plane.domain.capacity.scenario_history import (
    CapacityScenarioHistoryRepository,
    SavedIllustrativeCapacityPlanNotFoundError,
)

__all__ = [
    "CapacityPlanner",
    "CapacityScenarioHistoryRepository",
    "SavedIllustrativeCapacityPlanNotFoundError",
    "illustrative_capacity_plan",
]
