"""Certification contracts (Phase 6).

Defines the vocabulary and durable record shape for the "Certified test
dataset pipeline" `ROADMAP.md` describes:

```
INGEST -> PROFILE -> CLASSIFY -> SUBSET -> MASK ->
GENERATE OPTIONAL SYNTHETIC DATA -> VALIDATE -> CERTIFY -> PUBLISH
```

This module intentionally contains only data shapes (per the package
README's "no business logic" rule) — the actual gate-checking logic, the
enforced status state machine, and the tamper-evidence signature
mechanism live in
`services/data-plane/src/data_plane/certification/` (the data-plane
producer of these records), exactly the same split `subsetting.py`
(`IntegrityStatus` here, `validate_subset` there) and `masking.py`
(`MaskingTechnique` here, `MaskingEngine` there) already establish.

A dataset must NOT be publishable simply because masking ran
--------------------------------------------------------------
`problems_phase_03.md` P3-1 says this explicitly: Phase 3's own masking
validation (`data_plane.masking.validation`) is "not the full certified
test dataset pipeline" and a later certifier "should not simply trust
this module's own report." `CertificationReport` is the typed answer to
that requirement — it is a *new*, independent record built from (but not
equal to) every prior phase's own manifest/report, with its own set of
gates and its own enforced status lifecycle. See
`docs/CERTIFICATION_VS_MASKING.md` for the full, honest explanation of
why "masking ran" and "certified" are different claims.

Why six statuses, not the metadata plane's five-value `SnapshotStatus`
-----------------------------------------------------------------------
`snapshots.py`'s `SnapshotStatus` (`PENDING_CERTIFICATION -> CERTIFIED ->
PUBLISHED`, plus `REJECTED`/`EXPIRED`) already exists, but it is the
*metadata plane's* vocabulary for a registered snapshot record (Phase 7,
not yet implemented) and does not have a `DRAFT`/`PROCESSING` distinction
a certification *pipeline run in progress* needs, nor a `REVOKED` state
for a snapshot whose certification is later invalidated (e.g. a policy
defect discovered after publication). `CertificationStatus` is this
phase's own, narrower vocabulary for the certification pipeline's own
run lifecycle; a future Phase 7 snapshot registry integration would map
`CertificationStatus.PUBLISHED` to `SnapshotStatus.PUBLISHED` at the
point a certified dataset becomes a registered snapshot, not replace
either vocabulary with the other.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


class CertificationStatus(str, Enum):
    """The six-state lifecycle of one certification run.

    Enforced as a real state machine (not just documentation) by
    `data_plane.certification.state_machine.transition` — see that
    module for the allowed-transition table and
    `docs/CERTIFICATION_VS_MASKING.md` for why each transition is
    restricted the way it is.

    DRAFT
        A certification report has been created for a dataset but the
        pipeline has not started running gates yet.
    PROCESSING
        The pipeline is actively running VALIDATE-stage gate checks.
    FAILED
        One or more required gates failed. Terminal: a FAILED report is
        never publishable, and does not itself transition to any other
        state — a fresh certification run (a new report) is required
        after the underlying defect is fixed.
    CERTIFIED
        Every required gate passed. Publishable, but not yet published.
    PUBLISHED
        A certified dataset has been explicitly published -- the actual
        "safe to use in a lower environment" state.
    REVOKED
        A previously CERTIFIED or PUBLISHED dataset's certification has
        been invalidated after the fact (e.g. a defect discovered later
        in the policy or pipeline that produced it). Terminal.
    """

    DRAFT = "draft"
    PROCESSING = "processing"
    FAILED = "failed"
    CERTIFIED = "certified"
    PUBLISHED = "published"
    REVOKED = "revoked"


#: The allowed-transition table, as data (the *enforcement* -- raising on
#: an attempted transition not listed here -- lives in
#: `data_plane.certification.state_machine`, per this module's "no
#: business logic" rule). Documented here once so contracts and the
#: engine that enforces them never drift out of sync with each other's
#: understanding of "what is a valid transition."
CERTIFICATION_STATUS_TRANSITIONS: dict[CertificationStatus, frozenset[CertificationStatus]] = {
    CertificationStatus.DRAFT: frozenset({CertificationStatus.PROCESSING}),
    CertificationStatus.PROCESSING: frozenset(
        {CertificationStatus.CERTIFIED, CertificationStatus.FAILED}
    ),
    CertificationStatus.CERTIFIED: frozenset(
        {CertificationStatus.PUBLISHED, CertificationStatus.REVOKED}
    ),
    CertificationStatus.PUBLISHED: frozenset({CertificationStatus.REVOKED}),
    CertificationStatus.FAILED: frozenset(),
    CertificationStatus.REVOKED: frozenset(),
}


class CertificationGateType(str, Enum):
    """The eleven required certification gates (`ROADMAP.md` Phase 6).

    Each maps to exactly one check function in
    `data_plane.certification.gates`. See that module's docstrings for
    what each gate actually verifies and
    `docs/CERTIFICATION_VS_MASKING.md` for the policy decisions behind
    the gates that are not simple pass/fail re-derivations of an earlier
    phase's own report (e.g. `ORPHAN_DETECTION`'s "is
    `passed_with_known_orphans` acceptable?" question).
    """

    PHI_PII_POLICY_COVERAGE = "phi_pii_policy_coverage"
    MASKING_COMPLETION = "masking_completion"
    REFERENTIAL_INTEGRITY = "referential_integrity"
    SCHEMA_VALIDATION = "schema_validation"
    DATA_QUALITY_THRESHOLDS = "data_quality_thresholds"
    ROW_COUNT_RECONCILIATION = "row_count_reconciliation"
    ORPHAN_DETECTION = "orphan_detection"
    PROVENANCE = "provenance"
    MANIFEST_GENERATION = "manifest_generation"
    POLICY_VERSION_RECORDED = "policy_version_recorded"
    MASKING_VERSION_RECORDED = "masking_version_recorded"


class CertificationGateResult(BaseModel):
    """The outcome of running one certification gate."""

    gate: CertificationGateType
    passed: bool
    detail: str = Field(
        default="", description="Human-readable explanation of the outcome, always populated."
    )
    metrics: dict[str, str] = Field(
        default_factory=dict,
        description="Gate-specific numeric/text evidence (counts, thresholds, ids), stringified "
        "for stable JSON/audit-log serialization.",
    )


class CertificationStatusEvent(BaseModel):
    """One entry in a `CertificationReport.status_history` -- an
    append-only trail of every status transition this report has been
    through, who/what performed it, and why."""

    status: CertificationStatus
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    actor: str = Field(..., description="Identity or system that caused this transition.")
    reason: str = Field(default="", description="Why, e.g. a REVOKED reason.")


class CertificationReport(BaseModel):
    """The durable, machine-readable record of one certification run.

    This is the Phase 6 analogue of `SubsetManifest` (Phase 4) and
    `SyntheticGenerationManifest`/`MaskingRunReport` (Phases 5/3): a
    self-contained, typed artifact, except this one also carries an
    *enforced* status lifecycle (`CertificationStatus`) and an integrity
    signature (`integrity_signature`) rather than being a passive summary
    -- see `data_plane.certification.state_machine` and
    `data_plane.certification.signing`.
    """

    report_id: UUID = Field(default_factory=uuid4)
    version: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    status: CertificationStatus = CertificationStatus.DRAFT
    status_history: list[CertificationStatusEvent] = Field(default_factory=list)

    dataset_name: str = Field(
        ..., description="Human-readable identifier for the dataset/run being certified."
    )
    scale_profile: str = Field(default="unknown")

    subset_manifest_id: UUID | None = Field(
        default=None, description="`SubsetManifest.manifest_id` of the SUBSET stage input."
    )
    synthetic_generation_manifest_id: UUID | None = Field(
        default=None,
        description="`SyntheticGenerationManifest.manifest_id`, if the optional synthetic "
        "scenario stage ran.",
    )

    masking_policy_name: str = Field(default="")
    masking_policy_version: int = Field(default=0)
    masking_engine_version: str = Field(default="")

    gates: list[CertificationGateResult] = Field(default_factory=list)
    row_count_reconciliation: dict[str, str] = Field(
        default_factory=dict,
        description="Per-entity source -> selected -> masked -> final row-count trail, "
        "human-readable, built from Phase 4's SubsetManifest plus this run's own counts.",
    )

    integrity_signature: str | None = Field(
        default=None,
        description="Keyed HMAC signature over this report's substantive fields, computed by "
        "`data_plane.certification.signing.sign_report` at CERTIFY time and re-verified before "
        "any further status transition -- the tamper-evidence mechanism for a hand-edited JSON "
        "report file. See `docs/CERTIFICATION_VS_MASKING.md` for this mechanism's real limits.",
    )

    certified_at: datetime | None = None
    published_at: datetime | None = None
    revoked_at: datetime | None = None
    revoked_reason: str | None = None

    notes: str = Field(default="")

    @property
    def is_publishable(self) -> bool:
        """True only when this report's status is `CERTIFIED` -- the
        single condition `data_plane.certification.state_machine.publish`
        also enforces in code. Exposed here as a cheap, read-only
        convenience for callers that want to check before attempting a
        transition (e.g. a UI disabling a "Publish" button), never as a
        substitute for the enforced check itself.
        """

        return self.status is CertificationStatus.CERTIFIED

    @property
    def all_gates_passed(self) -> bool:
        return bool(self.gates) and all(g.passed for g in self.gates)


__all__ = [
    "CERTIFICATION_STATUS_TRANSITIONS",
    "CertificationGateResult",
    "CertificationGateType",
    "CertificationReport",
    "CertificationStatus",
    "CertificationStatusEvent",
]
