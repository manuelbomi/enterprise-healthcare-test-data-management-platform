"""Synthetic scenario generation contracts (Phase 5).

Phase 1 (`data_plane.reference_data`) already generates a wholly synthetic
estate and injects edge cases (nulls, duplicates, orphans, malformed
values, late-arriving data, schema drift) as part of *building* that
estate. This module is about a different, later pipeline stage
(`ARCHITECTURE.md`'s `... -> MASK -> GENERATE OPTIONAL SYNTHETIC DATA ->
VALIDATE -> ...`): supplementing an already-subsetted-and-masked dataset
(or producing a standalone dataset) with deliberately constructed
*scenario* records a QA/test engineer needs on demand -- "give me a
high-cost claim", "give me a claim referencing a member that doesn't
exist" -- which may not occur naturally, or often enough, in a random
subset.

Three data provenance categories must never be conflated (this phase's
core safety requirement -- "never allow synthetic records to be mistaken
for real records"):

- ``MASKED_PRODUCTION_LIKE`` -- real production values, transformed
  through the Phase 3 masking engine. Realistic distribution/values,
  but ultimately derived from a real row.
- ``SYNTHETIC`` -- wholly fabricated by this phase (or by Phase 1), no
  real row involved anywhere in its lineage, but schema-conformant and
  referentially valid (usable as positive-path test fixtures).
- ``NEGATIVE_TEST`` -- wholly fabricated, and *deliberately* schema-
  adjacent-but-broken (a dangling reference, an impossible business
  state, a missing required linkage) -- usable only as a fixture for
  exercising rejection/validation paths, never a "normal" record.

See `data_plane.synthetic` (`services/data-plane/src/data_plane/synthetic/`)
for the generator that produces rows carrying these tags, and
`docs/tutorial/05-synthetic-scenario-generation.md` for a worked
walkthrough.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class DataProvenance(str, Enum):
    """Where a row (or an entire dataset/batch) actually came from.

    This is the vocabulary the whole platform uses, from this phase
    forward, to answer "is this real (masked) data or not?" without
    ambiguity. Every row this phase writes carries one of these three
    values in a ``data_provenance`` column (see
    `data_plane.synthetic.provenance`); every dataset/manifest this phase
    produces also carries provenance-level rollups, so both a downstream
    program and a human reviewer can check provenance at whichever
    granularity they need.
    """

    #: Derived from a real production row, transformed by the Phase 3
    #: masking engine. Not synthetic -- the *shape and values* are
    #: masked-real, not fabricated.
    MASKED_PRODUCTION_LIKE = "masked_production_like"
    #: Wholly fabricated (no real row anywhere in its lineage), schema-
    #: conformant and referentially valid -- safe to treat as a normal
    #: positive-path record by anything that doesn't care about
    #: provenance.
    SYNTHETIC = "synthetic"
    #: Wholly fabricated and deliberately invalid/broken in a specific,
    #: documented way (dangling reference, impossible business state,
    #: missing required linkage) -- a negative-test fixture. Must never
    #: be treated as a normal record; a certification/validation pipeline
    #: that doesn't know to exclude these will (correctly) flag them.
    NEGATIVE_TEST = "negative_test"


class ScenarioType(str, Enum):
    """The eleven scenario categories this phase's promptbook requires.

    Each maps to exactly one generator function in
    `data_plane.synthetic.scenarios` and exactly one `DataProvenance`
    value (`data_plane.synthetic.provenance.SCENARIO_PROVENANCE`) --
    see that module's docstring for the reasoning behind each
    classification.
    """

    NORMAL_CLAIMS = "normal_claims"
    HIGH_COST_CLAIMS = "high_cost_claims"
    DUPLICATE_CLAIMS = "duplicate_claims"
    INVALID_CLAIM_REFERENCES = "invalid_claim_references"
    EXPIRED_COVERAGE = "expired_coverage"
    MISSING_PROVIDER = "missing_provider"
    UNUSUAL_PRESCRIPTION_COMBINATIONS = "unusual_prescription_combinations"
    MISSING_LABORATORY_VALUES = "missing_laboratory_values"
    BOUNDARY_DATES = "boundary_dates"
    NULL_HEAVY_RECORDS = "null_heavy_records"
    VERY_LARGE_CLAIM_HISTORIES = "very_large_claim_histories"


class ScenarioGenerationRecord(BaseModel):
    """What one scenario generator run actually produced.

    One of these exists per `ScenarioType` requested in a
    `SyntheticGenerationManifest.scenarios` list.
    """

    scenario: ScenarioType
    provenance: DataProvenance
    description: str = Field(
        default="", description="Human-readable summary of what this scenario batch contains."
    )
    row_counts: dict[str, int] = Field(
        default_factory=dict, description="Rows generated for this scenario, keyed by entity name."
    )
    anchor_ids: list[str] = Field(
        default_factory=list,
        description=(
            "The scenario-sub-range IDs (e.g. 'SYN-MBR-SCEN-000012') anchoring this batch, "
            "for traceability from the manifest straight to specific written rows."
        ),
    )


class SyntheticGenerationManifest(BaseModel):
    """The durable record of one synthetic scenario generation run.

    The Phase 5 analogue of `SubsetManifest` (Phase 4) and
    `MaskingRunReport` (Phase 3): a self-contained, typed artifact
    written next to the generated output
    (`synthetic_generation_manifest.json`) recording what scenarios were
    generated, how many rows of what, and -- this phase's specific
    safety requirement -- the full provenance breakdown, so a
    downstream consumer can verify no synthetic/negative-test row is
    silently miscounted as masked-production-like data.
    """

    manifest_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    mode: str = Field(
        ...,
        description=(
            "'augment' -- scenarios were merged into an existing masked/subsetted estate -- or "
            "'standalone' -- a scenario-only dataset with no masked-production-like input at all."
        ),
    )
    base_estate_dir: str | None = Field(
        default=None,
        description="Source directory read in 'augment' mode (None in 'standalone' mode).",
    )
    base_subset_manifest_id: UUID | None = Field(
        default=None,
        description=(
            "The `SubsetManifest.manifest_id` of the augmented input, when the base estate's own "
            "'subset_manifest.json' was found alongside it -- lets a manifest reader trace this "
            "run's lineage back through Phase 4's subsetting run, when that provenance exists."
        ),
    )
    seed: int = Field(..., description="Random seed used, for reproducibility.")
    id_prefix_convention: str = Field(
        default=(
            "Scenario-generated entity IDs use the sub-range 'SYN-<ENTITY>-SCEN-<seq>' "
            "(e.g. 'SYN-MBR-SCEN-000004'), distinct by construction from Phase 1 estate-native "
            "IDs ('SYN-<ENTITY>-<seq>', no 'SCEN' segment). Negative-test dangling references use "
            "'SYN-<ENTITY>-SCEN-NX-<tag>-<seq>' ('NX' = deliberately nonexistent)."
        ),
        description="Documents the ID convention so a reader never has to reverse-engineer it.",
    )
    scenarios: list[ScenarioGenerationRecord] = Field(default_factory=list)
    total_row_counts: dict[str, int] = Field(
        default_factory=dict, description="Total rows written per entity, across the whole output."
    )
    provenance_row_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Total rows written per DataProvenance value, across every entity.",
    )
    estimated_output_storage_bytes: int = Field(default=0, ge=0)

    def scenario_types(self) -> set[ScenarioType]:
        return {s.scenario for s in self.scenarios}


__all__ = [
    "DataProvenance",
    "ScenarioGenerationRecord",
    "ScenarioType",
    "SyntheticGenerationManifest",
]
