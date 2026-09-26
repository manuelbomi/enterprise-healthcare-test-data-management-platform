"""`CapacityPlanner` -- the control-plane half of Phase 8 capacity
planning: real, DB-backed aggregation of Phase 7's `DatasetVersion`/
`EnvironmentDatasetRequest` data into storage/compute footprint and
naive-vs-shared cost comparisons, plus a pure, configurable illustrative
percentage-of-production scenario model. See
`docs/adr/0013-capacity-planning-plane-split.md` for why this lives here
rather than alongside `data_plane.capacity`'s real, on-disk measurement.

`CapacityPlanner` never modifies `control_plane.domain.lifecycle` --
it is a pure *reader* of `LifecycleRepository`'s existing public
methods (`list_versions`, `list_requests`, `get_version`, `get_request`,
`resolve_policy`), the same "don't re-solve Phase 7, build on top of it"
principle `docs/problems/problems_phase_08.md` states explicitly.
"""

from __future__ import annotations

from uuid import UUID

from healthcare_tdm_contracts import (
    CapacityPlan,
    DatasetVersionFootprint,
    DatasetVersionStatus,
    EnvironmentCapacityDemand,
    IllustrativeCapacityPlan,
    IllustrativeCapacityScenario,
    VacuumCandidate,
)

from control_plane.domain.capacity import estimator
from control_plane.domain.lifecycle.repository import LifecycleRepository

#: DatasetVersion statuses that are always safe candidates for physical
#: deletion once unreferenced -- ACTIVE and (by definition, since it is
#: still selectable) ROLLED_BACK-while-referenced are deliberately
#: excluded; only a version nothing points at *and* that is no longer
#: eligible to be newly selected is a vacuum candidate. ROLLED_BACK is
#: included because, like EXPIRED/REVOKED, a version with zero
#: referencing environment requests and a terminal-for-now status is not
#: about to be selected by anything currently active -- see
#: `DatasetVersionStatus`'s docstring for why ROLLED_BACK can still be
#: selected again later (which is exactly why it is only a candidate
#: while unreferenced, re-checked live, never cached).
_VACUUM_ELIGIBLE_STATUSES = frozenset(
    {DatasetVersionStatus.EXPIRED, DatasetVersionStatus.REVOKED, DatasetVersionStatus.ROLLED_BACK}
)


class CapacityPlanner:
    """Real, DB-backed capacity planning over the Phase 7 lifecycle
    schema. One instance per request/unit-of-work, exactly like
    `LifecycleRepository` -- cheap to construct, holds only the
    repository reference."""

    def __init__(self, repository: LifecycleRepository) -> None:
        self._repository = repository

    # ------------------------------------------------------------------
    # Per-dataset-version footprint
    # ------------------------------------------------------------------

    def dataset_version_footprint(self, version_id: UUID | str) -> DatasetVersionFootprint:
        version = self._repository.get_version(version_id)
        total_rows = sum(version.row_counts.values())
        return DatasetVersionFootprint(
            version_id=version.version_id,
            dataset_name=version.dataset_name,
            version_number=version.version_number,
            status=version.status,
            storage_footprint_bytes=version.size_bytes,
            row_counts=version.row_counts,
            total_row_count=total_rows,
            retention_days=version.retention_days,
            referenced_by_environments=version.referenced_by_environments,
            estimated_compute_unit_hours=estimator.estimate_compute_unit_hours(total_rows),
        )

    # ------------------------------------------------------------------
    # Per-environment demand
    # ------------------------------------------------------------------

    def environment_capacity_demand(self, request_id: UUID | str) -> EnvironmentCapacityDemand:
        request = self._repository.get_request(request_id)
        version = self._repository.get_version(request.current_version_id)
        policy = self._repository.resolve_policy(request.environment, request.dataset_name)
        total_rows = sum(version.row_counts.values())

        refreshes_per_year = estimator.estimate_refreshes_per_year(
            policy.cadence_type, policy.interval_days
        )
        annual_volume = estimator.estimate_annual_processing_volume_rows(total_rows, refreshes_per_year)
        annual_compute = estimator.estimate_annual_compute_unit_hours(total_rows, refreshes_per_year)
        resolved_interval = None
        if refreshes_per_year is not None:
            resolved_interval = round(365.0 / refreshes_per_year)

        return EnvironmentCapacityDemand(
            request_id=request.request_id,
            environment=request.environment,
            dataset_name=request.dataset_name,
            current_version_id=version.version_id,
            current_version_number=version.version_number,
            attributed_storage_bytes=version.size_bytes,
            total_row_count=total_rows,
            refresh_cadence_type=policy.cadence_type,
            refresh_interval_days=resolved_interval,
            retention_days=version.retention_days,
            estimated_refreshes_per_year=refreshes_per_year,
            estimated_annual_processing_volume_rows=annual_volume,
            estimated_annual_compute_unit_hours=annual_compute,
        )

    # ------------------------------------------------------------------
    # Aggregate real capacity plan (naive vs. shared, both real numbers)
    # ------------------------------------------------------------------

    def capacity_plan(self, *, dataset_name: str | None = None) -> CapacityPlan:
        """The concrete, real-data answer to "how much does Phase 7's
        shared-immutable-snapshot architecture actually save": sums
        `DatasetVersion.size_bytes` once per environment request that
        references it (`naive_total_storage_bytes` -- what it would cost
        if every environment owned an independent copy) against summing
        it once per *distinct* version actually referenced
        (`shared_total_storage_bytes` -- what it actually costs today).
        Both numbers come from real, already-registered Phase 7 data.
        """

        requests = self._repository.list_requests(dataset_name=dataset_name)
        demands = [self.environment_capacity_demand(r.request_id) for r in requests]

        versions_by_id = {}
        naive_total = 0
        for demand in demands:
            naive_total += demand.attributed_storage_bytes
            if demand.current_version_id not in versions_by_id:
                versions_by_id[demand.current_version_id] = demand.attributed_storage_bytes

        shared_total = sum(versions_by_id.values())
        footprints = [self.dataset_version_footprint(vid) for vid in versions_by_id]
        savings = naive_total - shared_total
        savings_pct = (savings / naive_total) if naive_total else 0.0

        return CapacityPlan(
            dataset_name=dataset_name,
            dataset_version_footprints=footprints,
            environment_demands=demands,
            environment_count=len(requests),
            distinct_dataset_version_count=len(versions_by_id),
            naive_total_storage_bytes=naive_total,
            shared_total_storage_bytes=shared_total,
            storage_savings_bytes=savings,
            storage_savings_pct=savings_pct,
        )

    # ------------------------------------------------------------------
    # Vacuum candidates (real, read-only -- see docs/problems/problems_phase_08.md P8-3)
    # ------------------------------------------------------------------

    def vacuum_candidates(self, *, dataset_name: str | None = None) -> list[VacuumCandidate]:
        """Every registered `DatasetVersion` whose status is terminal-for-now
        (EXPIRED/REVOKED/ROLLED_BACK) *and* is currently referenced by
        zero `EnvironmentDatasetRequest`s -- real, live-computed
        (`DatasetVersion.referenced_by_environments` is never cached),
        never a stored/stale list. Identifies candidates only; does not
        delete anything (`docs/problems/problems_phase_08.md` P8-3)."""

        candidates: list[VacuumCandidate] = []
        for version in self._repository.list_versions(dataset_name=dataset_name):
            if version.status not in _VACUUM_ELIGIBLE_STATUSES:
                continue
            if version.referenced_by_environments:
                continue
            candidates.append(
                VacuumCandidate(
                    version_id=version.version_id,
                    dataset_name=version.dataset_name,
                    version_number=version.version_number,
                    status=version.status,
                    storage_uri=version.storage_uri,
                    reclaimable_bytes=version.size_bytes,
                    reason=(
                        f"status={version.status.value}, unreferenced by any environment request"
                    ),
                )
            )
        return candidates


def illustrative_capacity_plan(scenario: IllustrativeCapacityScenario) -> IllustrativeCapacityPlan:
    """A pure, stateless function of `scenario` -- no database access,
    no filesystem access. Computes `ROADMAP.md` Phase 8's "Production:
    100 TB, QA 10%, SIT 5%, UAT 15%" example (extended to all five
    example environments, see
    `healthcare_tdm_contracts.DEFAULT_ENVIRONMENT_CAPACITY_REQUIREMENTS`)
    as a real, runnable, configurable model:

    - `naive_total_bytes` -- what it would cost if every environment in
      `scenario.requirements` got its own independent physical copy,
      sized at its own `target_pct_of_production`.
    - `shared_total_bytes` -- what it would cost under Phase 7's real
      sharing mechanism, modeled by grouping requirements into
      `share_tier`s and sizing each tier's one shared snapshot to the
      *largest* requirement in that tier (a smaller requirement can
      safely consume a proportionally larger, over-provisioned shared
      snapshot; it can never safely consume a smaller one than its own
      requirement -- see `EnvironmentCapacityRequirement`'s docstring).

    Always clearly an *illustration*, scaled from a configurable
    (possibly hypothetical) `production_baseline_bytes` -- never
    conflated with `CapacityPlanner.capacity_plan`'s real, DB-backed
    numbers. See `docs/CAPACITY_COST_TRADEOFFS.md`.
    """

    per_environment_naive: dict[str, int] = {}
    tier_max_pct: dict[str, float] = {}
    for requirement in scenario.requirements:
        bytes_for_env = int(scenario.production_baseline_bytes * requirement.target_pct_of_production)
        per_environment_naive[requirement.environment.value] = bytes_for_env
        tier_max_pct[requirement.share_tier] = max(
            tier_max_pct.get(requirement.share_tier, 0.0), requirement.target_pct_of_production
        )

    naive_total = sum(per_environment_naive.values())
    per_tier_shared = {
        tier: int(scenario.production_baseline_bytes * pct) for tier, pct in tier_max_pct.items()
    }
    shared_total = sum(per_tier_shared.values())
    savings = naive_total - shared_total
    savings_pct = (savings / naive_total) if naive_total else 0.0

    return IllustrativeCapacityPlan(
        scenario=scenario,
        per_environment_naive_bytes=per_environment_naive,
        per_tier_shared_bytes=per_tier_shared,
        naive_total_bytes=naive_total,
        shared_total_bytes=shared_total,
        savings_bytes=savings,
        savings_pct=savings_pct,
    )


__all__ = ["CapacityPlanner", "illustrative_capacity_plan"]
