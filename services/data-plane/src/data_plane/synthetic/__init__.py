"""Synthetic data generation.

Generates wholly synthetic records — no real source row involved at all —
for scenarios where no safe source data exists in sufficient quantity
(e.g., rare-condition cohorts, edge-case volumes, load/performance testing
scale). Distinct from masking: masking transforms a real (synthetic-in-
this-repo, but structurally "real" from the platform's point of view)
record; synthetic generation fabricates one from a statistical/rule-based
model with no source record at all.

Phase 0 scope: placeholder module. Implemented in Phase 12. Design intent:
generation is driven by profiles learned from (already-masked/aggregate)
distribution statistics in the metadata plane, not by hardcoded fixture
values, so generated data scales in both volume and realism.
"""
