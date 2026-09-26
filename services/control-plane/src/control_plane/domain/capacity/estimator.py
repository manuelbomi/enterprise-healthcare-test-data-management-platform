"""Compute-demand and processing-volume heuristics (Phase 8).

Pure, dependency-free functions turning real row counts and a real
`RefreshPolicy` cadence (both already-registered Phase 7 data) into
illustrative compute-demand figures. These are honestly a documented
*assumption*, not a benchmark: `ROWS_PER_COMPUTE_UNIT_HOUR` is a
plausible, stated throughput figure for the kind of row-level work this
platform's pipeline does (subset + mask + certify), not a number derived
from any real job run in this repository. `ROADMAP.md` Phase 14 ("Scale
and performance engineering, PySpark benchmarks") has since happened and
produced real measured per-stage throughput figures
(`docs/SCALE_AND_PERFORMANCE.md`), but none of them is a single
"subset+mask+certify pipeline" number this constant could be replaced
with directly, and this module was not touched by that phase -- see
`docs/problems/problems_phase_08.md` P8-1 for the honest, still-open continuation.

What *is* real here: the row counts and cadence data this module
consumes (`DatasetVersion.row_counts`, `RefreshPolicy.cadence_type`/
`interval_days`), and the arithmetic applied to them. Only the
throughput assumption itself is illustrative.

Phase 18B benchmark cross-check (`docs/problems/problems_final_review.md` P3-2, still
not "benchmarked" -- see below for why the constant itself is
deliberately left unchanged): `docs/SCALE_AND_PERFORMANCE.md` section 3
records a real, measured `pandas_masking[full_estate]` throughput of
2,681 rows/sec at `performance` scale (766,252-row estate) -- the real
number closest in kind to what `ROWS_PER_COMPUTE_UNIT_HOUR` models
(single-process, row-level, every-table/every-technique masking work,
the same category this constant's docstring already names). Converted
to the same units, that is ~9.65M rows/hour, roughly **1.9x** this
module's assumed 5,000,000 -- i.e. the illustrative assumption is
*conservative* relative to the closest real measurement available, not
wildly off in either direction. This is still not a benchmark of this
constant (real "subset+mask+certify pipeline" throughput would also
include Phase 4 subsetting and Phase 6 certification-gate overhead this
comparison excludes, and the real number is single-machine
`local[*]`/plain-Python, not whatever "one compute unit" means in a real
deployment) -- exactly the gap `docs/problems/problems_phase_08.md` P8-1 already
named and this cross-check does not close. What it adds: a real,
cited order-of-magnitude sanity check that did not exist before, in
place of an assumption with zero real-world anchor at all.
"""

from __future__ import annotations

from healthcare_tdm_contracts import RefreshCadenceType

from control_plane.domain.lifecycle import cadence as cadence_mod

#: Illustrative assumption: how many rows one "compute unit" (loosely, a
#: single Spark executor doing subset+mask+certify row-level work) can
#: process in one hour. See this module's docstring -- not a benchmarked
#: figure.
ROWS_PER_COMPUTE_UNIT_HOUR: float = 5_000_000.0


def estimate_compute_unit_hours(total_row_count: int) -> float:
    """Illustrative compute-unit-hours to process `total_row_count` rows
    once, using `ROWS_PER_COMPUTE_UNIT_HOUR`."""

    if total_row_count <= 0:
        return 0.0
    return total_row_count / ROWS_PER_COMPUTE_UNIT_HOUR


def estimate_refreshes_per_year(
    cadence_type: RefreshCadenceType, interval_days: int | None
) -> float | None:
    """365 / the resolved refresh interval, or `None` for cadences with
    no fixed interval (RELEASE_DRIVEN, ON_DEMAND) -- reuses
    `control_plane.domain.lifecycle.cadence.resolve_interval_days` so
    this module's notion of "the interval" never drifts from the one the
    real scheduler (`RefreshOrchestrator`) actually uses."""

    resolved = cadence_mod.resolve_interval_days(cadence_type, interval_days)
    if resolved is None or resolved <= 0:
        return None
    return 365.0 / resolved


def estimate_annual_processing_volume_rows(
    total_row_count: int, refreshes_per_year: float | None
) -> float | None:
    """`total_row_count * refreshes_per_year`, or `None` if there is no
    fixed refresh cadence to project from."""

    if refreshes_per_year is None:
        return None
    return total_row_count * refreshes_per_year


def estimate_annual_compute_unit_hours(
    total_row_count: int, refreshes_per_year: float | None
) -> float | None:
    """`estimate_compute_unit_hours(total_row_count) * refreshes_per_year`,
    or `None` if there is no fixed refresh cadence to project from."""

    if refreshes_per_year is None:
        return None
    return estimate_compute_unit_hours(total_row_count) * refreshes_per_year


__all__ = [
    "ROWS_PER_COMPUTE_UNIT_HOUR",
    "estimate_annual_compute_unit_hours",
    "estimate_annual_processing_volume_rows",
    "estimate_compute_unit_hours",
    "estimate_refreshes_per_year",
]
