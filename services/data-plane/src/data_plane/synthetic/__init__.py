"""Synthetic test data generation (Phase 5).

Generates wholly synthetic *scenario* records -- no real source row
involved at all -- to supplement an already-subsetted-and-masked dataset
(or to produce a standalone scenario-only dataset) with specific test
scenarios a QA/test engineer needs on demand: a high-cost claim, a claim
referencing a member that doesn't exist, a member with an unusually large
claim history, and so on -- scenarios that may not occur naturally, or
often enough, in a random subset of even a large production-like estate.

This is distinct from `data_plane.reference_data` (Phase 1), which
generates the *entire* synthetic estate and injects its own edge cases
(nulls, duplicates, orphans, malformed values, late-arriving data, schema
drift) as part of building that estate from scratch. This package
operates one pipeline stage later (`ARCHITECTURE.md`'s
``... -> MASK -> GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> ...``):
it augments or supplements, rather than builds from nothing.

Every row this package writes (and every row already present in a base
estate it augments) carries an explicit `data_provenance` tag
(`healthcare_tdm_contracts.DataProvenance`:
``masked_production_like`` / ``synthetic`` / ``negative_test``) so a
synthetic or negative-test record can never be mistaken for a real
(masked) one -- see `provenance.py` for the full mechanism and
`docs/tutorial/05-synthetic-scenario-generation.md` for a worked
walkthrough.

Note: an earlier Phase 0 placeholder docstring here said "Implemented in
Phase 12" -- that was written before this repository's roadmap was
finalized. `ROADMAP.md` assigns this package to Phase 5
("Synthetic test data generation (scenario/edge-case data)"); this
docstring (and this package's actual implementation) now reflects that.
"""

from data_plane.synthetic.engine import GenerationResult, generate_synthetic_scenarios
from data_plane.synthetic.scenarios import DEFAULT_SCENARIO_COUNTS, SCENARIO_GENERATORS

__all__ = [
    "DEFAULT_SCENARIO_COUNTS",
    "SCENARIO_GENERATORS",
    "GenerationResult",
    "generate_synthetic_scenarios",
]
