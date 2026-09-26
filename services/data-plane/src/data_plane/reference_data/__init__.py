"""Reference synthetic healthcare data estate.

This package builds a completely SYNTHETIC, multi-system healthcare data
estate that stands in for what a large healthcare organization would need
to provision into its lower environments: enrollment/member data, claims,
clinical encounters/labs, pharmacy fills, and a supplemental external
partner feed, spread across five heterogeneous simulated source systems
(see ``docs`` at the repository root and ``README.md`` in this directory
for the full picture).

Relationship to the rest of the data plane
-------------------------------------------
This is deliberately **not** the same thing as ``data_plane.synthetic``
(Phase 12 in ``ROADMAP.md``). ``data_plane.synthetic`` will generate
wholly synthetic records *as a substitute for masking* when no safe
source row exists for a given production scenario (rare-condition
cohorts, edge-case volumes) — its inputs are learned distribution
statistics.

``data_plane.reference_data`` generates the *source-side* estate itself —
the reference synthetic healthcare schema and data that later phases
(discovery, subsetting, masking, snapshotting) operate on as if it were a
real organization's production systems. Every value in this estate is
fabricated (Faker-driven or rule-based); nothing here is derived from or
resembles any real person, organization, or dataset. See
``DATA_GOVERNANCE.md`` Part A for the rules this must follow.

No PHI/masking work happens in this package — see the phase's stop
condition in ``problems_phase_01.md`` / the spec. This package only
*produces* the realistic-but-fake estate that later phases will classify,
subset, and mask.
"""

from __future__ import annotations

from data_plane.reference_data.generator import EstateGenerator, GeneratedEstate
from data_plane.reference_data.scale import SCALE_PROFILES, ScaleProfile

__all__ = [
    "SCALE_PROFILES",
    "EstateGenerator",
    "GeneratedEstate",
    "ScaleProfile",
]
