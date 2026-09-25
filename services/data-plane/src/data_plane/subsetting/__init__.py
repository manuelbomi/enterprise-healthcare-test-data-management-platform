"""Referentially intact, production-scale data subsetting (Phase 4).

Given a source dataset and a sizing rule (e.g., "2% of patients", "exactly
10,000 patients", "50 patients per rare condition", "patients active in
Q1 2025", "active patients with a paid claim", "patients that exercise a
known edge case"), produces a smaller dataset that preserves the
relationships between rows across every table and every one of the five
simulated source systems -- the defining requirement that separates this
from a naive per-table ``LIMIT``/sample, which would produce orphaned
child rows.

Design: subsetting starts from the ``Member`` anchor entity, selects an
anchor set per one of six sizing strategies
(`healthcare_tdm_contracts.SubsettingStrategy`), then pulls every row in
every related table that references a selected anchor -- implemented as a
graph walk over the estate's known relationships, not hardcoded per
strategy. See `docs/tutorial/04-subsetting-and-referential-closure.md`.

Module map
-----------
- `estate_io` -- reads the real, on-disk Phase 1 estate into plain row
  dicts, per dataset, across all five source systems.
- `selection` -- the six anchor-selection strategies; each decides only
  *which Member IDs are selected*.
- `closure` -- the referential-closure graph walk: given a selected
  Member ID set, pulls every related row across all five source systems,
  and classifies any dangling reference found (pre-existing source orphan
  vs. a genuine engine bug).
- `negative_testing` -- the opt-in, explicit mechanism for intentionally
  injecting a dangling reference, for negative testing only.
- `validation` -- turns `closure`'s (and, optionally,
  `negative_testing`'s) findings into a three-way integrity verdict
  (`healthcare_tdm_contracts.IntegrityStatus`).
- `writer` -- writes the selected rows back to disk, mirroring the source
  estate's five-source-system layout.
- `manifest` -- assembles the `healthcare_tdm_contracts.SubsetManifest`
  a subsetting run produces.
- `engine` -- `run_subsetting`, the end-to-end orchestrator all of the
  above is wired together by.
- `cli` -- `python -m data_plane.subsetting.cli`, the command-line entry
  point.
"""

from data_plane.subsetting.engine import SubsettingRunResult, run_subsetting

__all__ = ["SubsettingRunResult", "run_subsetting"]
