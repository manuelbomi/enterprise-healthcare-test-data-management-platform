"""`CapacityScenarioHistoryRepository` -- real persistence for a saved,
point-in-time `IllustrativeCapacityPlan` snapshot.

Resolves `problems_final_review.md` P3-3 ("illustrative capacity
scenarios are stateless; nothing can be saved/compared over time,"
tracked since `problems_phase_08.md` P8-4): before this module existed,
both `GET /api/v1/capacity/illustrative-plan` and
`POST /api/v1/capacity/illustrative-plan` were pure, stateless
calculations -- nothing about a scenario a caller built (a hypothetical
production baseline, a set of per-environment requirements) or the plan
computed from it was ever persisted, so there was no way to save one,
come back later, and compare it against another.

Deliberately minimal, per the same discipline `control_plane.domain.capacity`'s
own module docstring already states for this whole package ("never
modifies `control_plane.domain.lifecycle`... a pure reader"): this
module does not re-implement any of Phase 8's capacity math
(`control_plane.domain.capacity.planner.illustrative_capacity_plan`
remains the only place that logic lives). It only gives an already-fully-
computed `IllustrativeCapacityPlan` (already a self-contained,
serializable snapshot -- see that contract's own docstring) a stable id
and a `created_at` a caller can list/sort by, so "compare over time"
becomes "list two saved plans and diff their already-typed fields
client-side," not a new comparison engine.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from healthcare_tdm_contracts import IllustrativeCapacityPlan
from sqlalchemy.orm import Session

from control_plane.db.models import IllustrativeCapacityPlanRow


class SavedIllustrativeCapacityPlanNotFoundError(LookupError):
    """No `IllustrativeCapacityPlanRow` exists for the given identifier."""


class CapacityScenarioHistoryRepository:
    """Real, DB-backed append-only history of saved
    `IllustrativeCapacityPlan` snapshots. Mirrors
    `control_plane.domain.lifecycle.repository.LifecycleRepository`'s
    session-based construction convention exactly."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save_plan(self, plan: IllustrativeCapacityPlan, *, created_by: str) -> uuid.UUID:
        """Persist `plan` (already computed by
        `illustrative_capacity_plan`) as a new, immutable historical
        record. Returns the new `saved_plan_id` -- distinct from
        `plan.scenario.scenario_id`, since the same scenario could in
        principle be saved more than once (e.g. re-run after a
        `DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS` change) and each save
        is its own historical point, not an update to a prior one."""

        saved_plan_id = uuid.uuid4()
        row = IllustrativeCapacityPlanRow(
            saved_plan_id=str(saved_plan_id),
            label=plan.scenario.label,
            plan_json=plan.model_dump_json(),
            created_by=created_by,
            created_at=datetime.now(timezone.utc),
        )
        self._session.add(row)
        self._session.flush()
        return saved_plan_id

    def list_plans(self) -> list[tuple[uuid.UUID, str, datetime, IllustrativeCapacityPlan]]:
        """Every saved plan, oldest first -- `(saved_plan_id, created_by,
        created_at, plan)` -- the shape a caller wanting "compare over
        time" needs: enough to label each entry and the full typed plan
        to diff against another."""

        rows = (
            self._session.query(IllustrativeCapacityPlanRow)
            .order_by(IllustrativeCapacityPlanRow.created_at.asc())
            .all()
        )
        return [
            (
                uuid.UUID(row.saved_plan_id),
                row.created_by,
                _as_aware_utc(row.created_at),
                IllustrativeCapacityPlan.model_validate_json(row.plan_json),
            )
            for row in rows
        ]

    def get_plan(
        self, saved_plan_id: uuid.UUID | str
    ) -> tuple[uuid.UUID, str, datetime, IllustrativeCapacityPlan]:
        """`(saved_plan_id, created_by, created_at, plan)` for one saved
        record -- the same shape as one entry of `list_plans()`, so a
        caller fetching a single saved plan sees exactly the same fields
        a list entry would."""

        row = self._session.get(IllustrativeCapacityPlanRow, str(saved_plan_id))
        if row is None:
            raise SavedIllustrativeCapacityPlanNotFoundError(
                f"No saved illustrative capacity plan with saved_plan_id={saved_plan_id!r}."
            )
        return (
            uuid.UUID(row.saved_plan_id),
            row.created_by,
            _as_aware_utc(row.created_at),
            IllustrativeCapacityPlan.model_validate_json(row.plan_json),
        )


def _as_aware_utc(value: datetime) -> datetime:
    """Same SQLite-naive-DateTime handling every other module in this
    package already documents (see e.g.
    `control_plane.platform.scheduler_lock._as_aware_utc`) -- every
    `created_at` this repository writes is UTC by construction, so a
    naive value read back is always safe to re-attach `timezone.utc` to."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


__all__ = [
    "CapacityScenarioHistoryRepository",
    "SavedIllustrativeCapacityPlanNotFoundError",
]
