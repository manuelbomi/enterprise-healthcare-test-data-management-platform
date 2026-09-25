"""Referential-integrity-preserving data subsetting.

Given a source dataset and a sizing rule (e.g., "2% of patients, all
related claims and encounters, at least N rows per rare category"),
produces a smaller dataset that preserves the relationships between rows
across tables — the defining requirement that separates this from a naive
per-table LIMIT/sample, which would produce orphaned child rows.

Phase 0 scope: placeholder module. Implemented in Phase 8 (single-system)
and extended in Phase 10 (cross-system). Design intent: subsetting starts
from an "anchor" entity (typically patient), selects an anchor set per the
sizing rule, then pulls every row in every related table that references a
selected anchor — implemented as a graph walk over the known foreign-key
relationships in the metadata plane's catalog, not hardcoded per dataset.
"""
