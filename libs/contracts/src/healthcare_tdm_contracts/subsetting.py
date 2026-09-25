"""Subsetting contracts.

Defines the vocabulary this platform uses to describe *how* a
referentially intact subset of the synthetic estate was selected
(:class:`SubsettingStrategy`) and the durable record of what a subsetting
run actually produced (:class:`SubsetManifest`) -- the Phase 4 analogue of
`masking.py`'s ``MaskingPolicy`` / `catalog.py`'s ``CatalogEntry``: a typed
contract shared between the data-plane producer
(`services/data-plane/src/data_plane/subsetting/`) and any future consumer
(control-plane job tracking, the metadata plane's snapshot registry -- see
ARCHITECTURE.md section 2.3, not implemented yet; tracked in
`problems_phase_04.md`).

See `docs/tutorial/04-subsetting-and-referential-closure.md` for a worked
walkthrough of the graph-walk/referential-closure mechanism every one of
the six strategies below is built on top of.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class SubsettingStrategy(str, Enum):
    """The six population-selection strategies this phase implements.

    Every strategy only decides *which anchor entities (Members) are
    selected*. Once the anchor population is fixed, the exact same
    referential-closure graph walk
    (`data_plane.subsetting.closure.build_closure`) pulls every related
    row for every strategy identically -- see
    `docs/tutorial/04-subsetting-and-referential-closure.md`. This is a
    deliberate design point: the six strategies differ only in *anchor
    selection*, never in how relationships are traversed, which is what
    guarantees every one of them produces a referentially closed subset.
    """

    #: A random sample of N% of the source Member population.
    PERCENTAGE = "percentage"
    #: An exact target Member count (capped at the available population).
    FIXED_POPULATION = "fixed_population"
    #: A sample drawn proportionally (or with a fixed count-per-group) from
    #: named strata of the Member population (e.g. by gender).
    STRATIFIED = "stratified"
    #: Members with at least one claim (or other dated event) whose date
    #: falls within an explicit ``[start, end]`` window.
    DATE_WINDOW = "date_window"
    #: Members matching an explicit business predicate (e.g. "active
    #: coverage AND at least one paid claim").
    BUSINESS_RULE = "business_rule"
    #: Members touched by one or more of the Phase 1 estate's injected
    #: edge cases (orphan references, malformed values, missing children,
    #: duplicates, ...) -- a population deliberately over-weighted with
    #: the exact scenarios negative/edge-case QA testing needs.
    RISK_EDGE_CASE = "risk_edge_case"


class IntegrityStatus(str, Enum):
    """Outcome of a subset's post-selection referential integrity check.

    See `data_plane.subsetting.validation` for the algorithm and
    `data_plane/subsetting/README.md` ("Orphans: pre-existing vs.
    engine-introduced") for the full explanation of why a subset can
    legitimately contain dangling references without that being a defect.
    """

    #: No dangling relationships of any kind: every FK-shaped reference in
    #: the subset resolves to a row also present in the subset, or the
    #: source row had no such reference to begin with.
    PASSED = "passed"
    #: The subset contains one or more dangling references that were
    #: already present in the *source* estate (Phase 1's injected orphan
    #: edge cases, `reference_data/edge_cases.py`) and/or were
    #: intentionally injected by this run for negative testing -- expected
    #: and reported, not a defect in the subsetting engine's selection
    #: logic. See `known_orphan_counts` / `injected_negative_test_orphan_counts`.
    PASSED_WITH_KNOWN_ORPHANS = "passed_with_known_orphans"
    #: The subsetting engine itself introduced a dangling reference that
    #: does not trace back to a pre-existing source orphan or an
    #: intentional negative-test injection -- a real bug in
    #: selection/closure logic. A subset with this status must never be
    #: published.
    FAILED = "failed"


class SubsetSelectionCriteria(BaseModel):
    """The concrete parameters a subsetting run was invoked with.

    ``parameters`` is intentionally a free-form string-keyed dict
    (mirroring `MaskingRule.parameters`) because each strategy has a
    different natural parameter shape -- see
    `data_plane.subsetting.selection` for the exact parameter names each
    `SubsettingStrategy` reads.
    """

    strategy: SubsettingStrategy
    parameters: dict[str, str] = Field(default_factory=dict)
    description: str = Field(
        default="", description="Human-readable summary of what was selected and why."
    )
    negative_testing: bool = Field(
        default=False,
        description=(
            "True when this run intentionally injected one or more "
            "dangling references for negative testing "
            "(`data_plane.subsetting.negative_testing`), on top of "
            "whatever pre-existing source orphans the selection happened "
            "to carry forward."
        ),
    )


class RelationshipEdge(BaseModel):
    """One traversed edge of the referential-closure graph walk, with the
    row count it contributed to the subset.

    ``parent_entity``/``child_entity`` name the two ends of the
    relationship (e.g. ``Member`` -> ``Coverage``); ``edge_count`` is how
    many child rows were pulled into the subset because they referenced a
    selected parent row (or, for reference/code tables such as Diagnosis,
    how many distinct codes were pulled in because a selected child row
    referenced them).
    """

    parent_entity: str
    child_entity: str
    edge_count: int = Field(..., ge=0)


class SubsetManifest(BaseModel):
    """The durable record of one subsetting run: what was asked for, what
    was produced, and whether it is referentially sound.

    This is the Phase 4 analogue of `MaskingRunReport`
    (`data_plane.masking.dataset_masker`), promoted to a real, versioned
    `libs/contracts` shape rather than a data-plane-local dataclass
    because a manifest is meant to be a durable, cross-plane artifact: the
    future metadata plane's snapshot registry
    (`healthcare_tdm_contracts.snapshots.SnapshotRecord`) is expected to
    reference a produced subset the same way it already references a
    ``source_job_id`` -- see `problems_phase_04.md` for the tracked gap
    until that wiring exists.
    """

    manifest_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    scale_profile: str = Field(
        ..., description="Named scale profile of the SOURCE estate this subset was drawn from."
    )
    anchor_entity: str = Field(
        default="Member", description="The entity every other entity's inclusion is anchored to."
    )
    selection: SubsetSelectionCriteria
    source_counts: dict[str, int] = Field(
        default_factory=dict, description="Row count per entity in the source estate."
    )
    selected_counts: dict[str, int] = Field(
        default_factory=dict, description="Row count per entity actually written to the subset."
    )
    relationship_edges: list[RelationshipEdge] = Field(
        default_factory=list,
        description="Every relationship-graph edge traversed to build this subset, with counts.",
    )
    filter_criteria: dict[str, str] = Field(
        default_factory=dict,
        description="Flattened, human-readable filter criteria applied (dates, thresholds, rule names, ...).",
    )
    estimated_source_storage_bytes: int = Field(default=0, ge=0)
    estimated_subset_storage_bytes: int = Field(default=0, ge=0)
    integrity_status: IntegrityStatus
    known_orphan_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Pre-existing source-estate orphans (Phase 1 edge cases) that "
            "legitimately appear in this subset, keyed by relationship "
            "name (e.g. 'claim.provider_id')."
        ),
    )
    injected_negative_test_orphan_counts: dict[str, int] = Field(
        default_factory=dict,
        description=(
            "Dangling references this run deliberately injected for "
            "negative testing, keyed by relationship name. Zero unless "
            "`selection.negative_testing` is True."
        ),
    )
    integrity_findings: list[str] = Field(
        default_factory=list,
        description="Human-readable integrity check results, one line per relationship checked.",
    )

    def selection_ratio(self, entity: str) -> float | None:
        """Fraction of `entity`'s source rows that made it into the
        subset, or ``None`` if `entity` had zero source rows (avoids a
        division-by-zero footgun for callers building a summary table).
        """

        source = self.source_counts.get(entity)
        if not source:
            return None
        return self.selected_counts.get(entity, 0) / source


__all__ = [
    "IntegrityStatus",
    "RelationshipEdge",
    "SubsetManifest",
    "SubsetSelectionCriteria",
    "SubsettingStrategy",
]
