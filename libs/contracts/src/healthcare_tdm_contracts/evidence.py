"""Audit Evidence Package contract (Phase 13).

`ROADMAP.md` Phase 13 ("Auditability and Compliance Evidence") asks for
an Audit Evidence Package containing a dataset manifest, classification
summary, masking report, integrity report, quality report, policy
versions, approvals, lineage, timestamps, and hash/checksum metadata.

This module defines only the *shape* of that package (per the package
README's "no business logic" rule, the same split every other contract
module here follows) -- the actual aggregation logic (reading
`DatasetVersion`, `MaskingPolicyVersion`/`PolicyApproval`,
`EnvironmentDatasetRequest`/`ConsumerDatasetRequest`,
`RefreshRunRecord`/`RollbackRecord`, and `AuditEvent` rows, and computing
the bundle checksum) lives in
`control_plane.domain.evidence.EvidenceRepository` -- see
`docs/adr/0016-audit-evidence-lives-in-control-plane.md` for why.

**Honest scope note** -- read before treating this as more than it is:
`CertificationReport` (Phase 6) and `SubsetManifest` (Phase 4) are NOT
durably stored anywhere in `services/control-plane`'s database (only a
few scalar fields and a bare `certification_report_id` are). This
package can only embed them verbatim if the caller supplies the actual
artifacts when requesting the package -- exactly the same "the caller
provides the full report, the metadata plane persists only a
summary/reference" pattern
`control_plane.domain.lifecycle.repository.LifecycleRepository.register_dataset_version`
already uses for `CertificationReport`. When they are not supplied,
`integrity_report`/`quality_report`/the certification/subset lineage
fields are left empty, and `provenance_notes` says so explicitly --
never silently fabricated. See `problems_phase_13.md` P13-1.

**This package does not itself guarantee HIPAA (or any other
regulatory) compliance.** It is evidence an organization's own
privacy/security/compliance program can use in support of its own
determinations -- see `docs/COMPLIANCE_EVIDENCE.md` for the full,
honest explanation, matching the tone `docs/CERTIFICATION_VS_MASKING.md`
and `docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` already set for this
repository.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from healthcare_tdm_contracts.audit import AuditEvent
from healthcare_tdm_contracts.certification import CertificationReport
from healthcare_tdm_contracts.governance import ConsumerDatasetRequest, MaskingPolicyVersion, PolicyApproval
from healthcare_tdm_contracts.lifecycle import (
    DatasetVersion,
    EnvironmentDatasetRequest,
    RefreshRunRecord,
    RollbackRecord,
)
from healthcare_tdm_contracts.subsetting import SubsetManifest

#: The one, short, honest sentence this package always carries. Referenced
#: verbatim by `AuditEvidencePackage.compliance_disclaimer`'s default and
#: repeated in `docs/COMPLIANCE_EVIDENCE.md` so the same claim (and no
#: stronger one) appears everywhere this package is described.
COMPLIANCE_DISCLAIMER = (
    "This Audit Evidence Package is evidence in support of an organization's own "
    "privacy/security/compliance program (e.g. a HIPAA compliance program). It is NOT "
    "itself a certification, attestation, or guarantee of HIPAA or any other regulatory "
    "compliance -- that determination is made by an organization's own qualified "
    "compliance/legal personnel, informed by evidence such as this package, not by software."
)


class AuditEvidencePackage(BaseModel):
    """A single, coherent, checksum-verified bundle of evidence about one
    `DatasetVersion` -- who requested/accessed/approved it, what source
    and policies produced it, how it has been refreshed/rolled
    back/revoked, and (when supplied) its certification/subsetting
    provenance.
    """

    package_id: UUID = Field(default_factory=uuid4)
    generated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    generated_by: str = Field(..., description="Identity of the user/system that generated this package.")

    dataset_version_id: UUID
    dataset_name: str
    version_number: int

    # -- "what source was used", "when generated", "where provisioned" --
    dataset_manifest: DatasetVersion
    environment_requests: list[EnvironmentDatasetRequest] = Field(
        default_factory=list,
        description="Every environment currently or previously pointed at this dataset -- 'where "
        "provisioned'.",
    )
    consumer_requests: list[ConsumerDatasetRequest] = Field(
        default_factory=list,
        description="Every business-consumer request against this dataset_name -- 'who requested it'.",
    )

    # -- classification summary (Phase 2) --
    classification_summary: dict[str, object] = Field(
        default_factory=dict,
        description="Catalog-derived classification rollup for this dataset_name (column/category "
        "counts). Empty (with a provenance_notes entry) if no catalog artifact was available.",
    )

    # -- masking policy/version + approvals (Phase 3/10) --
    masking_policy_version: MaskingPolicyVersion | None = Field(
        default=None,
        description="The governed Phase 10 MaskingPolicyVersion matching this dataset version's "
        "masking_policy_name/masking_policy_version, if one was ever drafted through governance.",
    )
    masking_policy_approvals: list[PolicyApproval] = Field(default_factory=list)

    # -- certification results, subset policy (Phase 6/4; caller-supplied) --
    certification_report: CertificationReport | None = Field(
        default=None,
        description="Embedded verbatim if the caller supplied it when requesting this package -- "
        "see this module's docstring for why control-plane cannot re-derive it on its own.",
    )
    subset_manifest: SubsetManifest | None = Field(default=None, description="Same caveat as certification_report.")

    # -- integrity/quality reports (derived from certification_report's gates, when present) --
    integrity_report: dict[str, object] = Field(default_factory=dict)
    quality_report: dict[str, object] = Field(default_factory=dict)

    # -- refresh / revocation / rollback history (Phase 7) --
    refresh_history: list[RefreshRunRecord] = Field(default_factory=list)
    rollback_history: list[RollbackRecord] = Field(default_factory=list)
    revocation: dict[str, str] = Field(
        default_factory=dict,
        description="revoked_at/revoked_by/revoked_reason/status, flattened to strings for stable "
        "JSON -- empty values when never revoked.",
    )

    # -- "who accessed/approved it" (Phase 11 audit log + Phase 13 access event) --
    audit_trail: list[AuditEvent] = Field(
        default_factory=list,
        description="Every real AuditEvent this dataset version (or a request that references it) "
        "has produced -- registrations, revocations, refreshes, rollbacks, policy approvals/"
        "rejections, access-denials, and DATASET_VERSION_ACCESSED events.",
    )

    # -- lineage --
    lineage: dict[str, str] = Field(
        default_factory=dict,
        description="IDs tying every pipeline stage together (certification_report_id, "
        "subset_manifest_id, masking_policy_version_id, ...), stringified for stable JSON.",
    )

    # -- tamper-evidence for this bundle itself --
    #: Phase 18A (`problems_final_review.md` P1-7): upgraded from a
    #: plain, unkeyed "sha256" to a keyed "hmac-sha256", matching
    #: `data_plane.certification.signing`'s guarantee for a
    #: `CertificationReport` -- see
    #: `control_plane.platform.evidence_signing` and
    #: `docs/TAMPER_EVIDENCE_LIMITATIONS.md`.
    bundle_checksum_algorithm: str = Field(default="hmac-sha256")
    bundle_checksum: str = Field(
        default="",
        description="Keyed HMAC-SHA256 digest over this package's own canonical JSON (every field "
        "except this one), computed by EvidenceRepository (control_plane.platform.evidence_signing) "
        "at generation time. See docs/TAMPER_EVIDENCE_LIMITATIONS.md for this mechanism's honest "
        "limits -- it is a real tamper-DETECTION mechanism, not a non-repudiation signature immune "
        "to someone holding both database access and the signing key.",
    )

    provenance_notes: list[str] = Field(
        default_factory=list,
        description="Human-readable notes about what could NOT be included and why (e.g. no "
        "certification_report supplied, no catalog artifact available) -- never silently omitted.",
    )

    compliance_disclaimer: str = Field(default=COMPLIANCE_DISCLAIMER)


__all__ = ["COMPLIANCE_DISCLAIMER", "AuditEvidencePackage"]
