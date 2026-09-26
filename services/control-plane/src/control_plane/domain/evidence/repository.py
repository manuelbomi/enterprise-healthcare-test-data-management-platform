"""`EvidenceRepository` -- builds a Phase 13 `AuditEvidencePackage` for
one dataset version.

This is a *read-mostly* aggregator, not a new source of truth: every
substantive field it fills in is a real re-export of an already-real
Phase 2/6/7/10/11 artifact --

- the dataset manifest and provisioning/refresh/rollback/revocation
  history come from `control_plane.domain.lifecycle.LifecycleRepository`
  (Phase 7, extended this phase with `list_refresh_runs`/
  `list_rollback_events` -- see `docs/problems/problems_phase_13.md`);
- the masking policy version + its approval trail come from
  `control_plane.domain.governance.GovernanceRepository` (Phase 10);
- the classification summary comes from
  `control_plane.catalog.CatalogRepository` (Phase 2);
- the audit trail comes from `control_plane.platform.audit.AuditLogRepository`
  (Phase 11, extended this phase with `DATASET_VERSION_ACCESSED`/
  `EVIDENCE_PACKAGE_GENERATED`);
- the certification report / subset manifest are embedded verbatim
  *only* if the caller supplies them -- `services/control-plane` does
  not durably store either (see `healthcare_tdm_contracts.evidence`'s
  module docstring and `docs/problems/problems_phase_13.md` P13-1).

The one genuinely new piece of business logic here is the aggregation
itself (which rows to pull for a given dataset version, how to merge
several `AuditEvent` queries into one deduplicated, time-ordered trail)
and the bundle checksum. See `docs/adr/0016-audit-evidence-lives-in-
control-plane.md` for why this lives in `services/control-plane` rather
than `services/governance-service`, mirroring ADR-0014/0015's reasoning.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from healthcare_tdm_contracts import (
    AuditEvent,
    AuditEventType,
    AuditEvidencePackage,
    CertificationGateType,
    CertificationReport,
    SubsetManifest,
)
from sqlalchemy.orm import Session

from control_plane.catalog import CatalogNotAvailableError, CatalogRepository
from control_plane.domain.governance import GovernanceRepository
from control_plane.domain.governance.errors import MaskingPolicyVersionNotFoundError
from control_plane.domain.lifecycle import LifecycleRepository
from control_plane.platform import evidence_signing
from control_plane.platform.audit import AuditLogRepository
from control_plane.platform.evidence_signing import compute_bundle_checksum, verify_bundle_checksum

#: Certification gates that answer "is this dataset referentially/
#: structurally sound" -- the "integrity report" the phase brief asks
#: for. `PROVENANCE`/`MANIFEST_GENERATION`/`POLICY_VERSION_RECORDED`/
#: `MASKING_VERSION_RECORDED` are deliberately left out of both groups
#: below (they answer "was this pipeline run properly documented," not
#: "is the data referentially sound" or "does the data meet quality
#: thresholds") and instead surface in `lineage`/the raw
#: `certification_report.gates` list, which is embedded in full whenever
#: a report is supplied.
_INTEGRITY_GATES = frozenset(
    {
        CertificationGateType.REFERENTIAL_INTEGRITY,
        CertificationGateType.ORPHAN_DETECTION,
        CertificationGateType.ROW_COUNT_RECONCILIATION,
    }
)
#: Certification gates that answer "does this dataset meet data-quality
#: expectations" -- the "quality report."
_QUALITY_GATES = frozenset(
    {
        CertificationGateType.DATA_QUALITY_THRESHOLDS,
        CertificationGateType.SCHEMA_VALIDATION,
        CertificationGateType.PHI_PII_POLICY_COVERAGE,
        CertificationGateType.MASKING_COMPLETION,
    }
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


class EvidenceRepository:
    """Builds one `AuditEvidencePackage` per call. Composes
    `LifecycleRepository`/`GovernanceRepository`/`AuditLogRepository`
    sharing this repository's own `Session`, and an independent
    `CatalogRepository` (a separate, file-backed artifact reader per
    ADR-0009 -- not part of this schema/session, so a missing catalog
    file degrades gracefully rather than failing the whole package)."""

    def __init__(self, session: Session, *, catalog_repository: CatalogRepository) -> None:
        self._session = session
        self.lifecycle = LifecycleRepository(session)
        self.governance = GovernanceRepository(session)
        self.audit = AuditLogRepository(session)
        self._catalog = catalog_repository

    def build_evidence_package(
        self,
        version_id: UUID | str,
        *,
        generated_by: str,
        certification_report: CertificationReport | None = None,
        subset_manifest: SubsetManifest | None = None,
    ) -> AuditEvidencePackage:
        """Aggregate every real artifact this control plane holds about
        `version_id` into one `AuditEvidencePackage`, records an
        `EVIDENCE_PACKAGE_GENERATED` audit event, and returns the
        package with its `bundle_checksum` computed.

        Raises `control_plane.domain.lifecycle.DatasetVersionNotFoundError`
        if `version_id` does not exist -- the same exception the rest of
        this service's endpoints already translate to HTTP 404.
        """

        version = self.lifecycle.get_version(version_id)  # raises DatasetVersionNotFoundError
        provenance_notes: list[str] = []

        # -- provisioning ("where"), consumer requests ("who requested") --
        environment_requests = self.lifecycle.list_requests(dataset_name=version.dataset_name)
        consumer_requests = self.governance.list_consumer_requests(dataset_name=version.dataset_name)

        # -- refresh / rollback history --
        refresh_history = self.lifecycle.list_refresh_runs(dataset_name=version.dataset_name)
        rollback_history = self.lifecycle.list_rollback_events(dataset_name=version.dataset_name)

        # -- revocation --
        revocation = {
            "status": version.status.value,
            "revoked_at": version.revoked_at.isoformat() if version.revoked_at else "",
            "revoked_by": version.revoked_by or "",
            "revoked_reason": version.revoked_reason or "",
            "rolled_back_at": version.rolled_back_at.isoformat() if version.rolled_back_at else "",
        }

        # -- classification summary (degrades gracefully) --
        classification_summary: dict[str, object] = {}
        try:
            entries = self._catalog.list_entries(dataset=version.dataset_name)
            by_category: dict[str, int] = {}
            for entry in entries:
                key = entry.classification.category.value if entry.classification.category else "unknown"
                by_category[key] = by_category.get(key, 0) + 1
            classification_summary = {
                "dataset": version.dataset_name,
                "column_count": len(entries),
                "by_category": by_category,
                "needs_review": sum(1 for e in entries if e.classification.needs_review),
            }
            if not entries:
                provenance_notes.append(
                    f"No catalog entries found for dataset_name={version.dataset_name!r} -- "
                    "classification_summary is present but empty."
                )
        except CatalogNotAvailableError as exc:
            provenance_notes.append(f"Classification summary omitted: {exc}")

        # -- masking policy version + approvals --
        masking_policy_version = None
        masking_policy_approvals: list = []
        try:
            candidates = self.governance.list_policy_versions(policy_name=version.masking_policy_name)
            for candidate in candidates:
                if candidate.policy_version == version.masking_policy_version:
                    masking_policy_version = candidate
                    break
            if masking_policy_version is not None:
                masking_policy_approvals = self.governance.list_policy_approvals(
                    masking_policy_version.policy_version_id
                )
            else:
                provenance_notes.append(
                    f"No governed MaskingPolicyVersion found for policy_name="
                    f"{version.masking_policy_name!r} policy_version={version.masking_policy_version!r} "
                    "-- this dataset version may have been registered against a masking policy that "
                    "was never drafted through Phase 10 governance."
                )
        except MaskingPolicyVersionNotFoundError as exc:  # pragma: no cover - defensive
            provenance_notes.append(f"Masking policy version lookup failed: {exc}")

        # -- certification / subset provenance (caller-supplied only) --
        integrity_report: dict[str, object] = {}
        quality_report: dict[str, object] = {}
        lineage: dict[str, str] = {"certification_report_id": str(version.certification_report_id)}
        if certification_report is not None:
            for gate in certification_report.gates:
                entry = {"passed": gate.passed, "detail": gate.detail, "metrics": gate.metrics}
                if gate.gate in _INTEGRITY_GATES:
                    integrity_report[gate.gate.value] = entry
                if gate.gate in _QUALITY_GATES:
                    quality_report[gate.gate.value] = entry
            if certification_report.subset_manifest_id is not None:
                lineage["subset_manifest_id"] = str(certification_report.subset_manifest_id)
            if certification_report.synthetic_generation_manifest_id is not None:
                lineage["synthetic_generation_manifest_id"] = str(
                    certification_report.synthetic_generation_manifest_id
                )
        else:
            provenance_notes.append(
                "No CertificationReport was supplied to this evidence package request -- "
                "integrity_report/quality_report are empty. Supply the Phase 6 CertificationReport "
                "produced for this dataset version to include gate-level integrity/quality evidence."
            )
        if subset_manifest is not None:
            lineage["subset_manifest_id"] = str(subset_manifest.manifest_id)
        elif certification_report is None:
            provenance_notes.append(
                "No SubsetManifest was supplied to this evidence package request -- subset policy "
                "detail is limited to whatever a supplied CertificationReport's own "
                "row_count_reconciliation/lineage fields carry."
            )
        if masking_policy_version is not None:
            lineage["masking_policy_version_id"] = str(masking_policy_version.policy_version_id)

        # -- audit trail: dedup-merge every subject this dataset touches --
        subjects = {str(version.version_id)}
        subjects.update(str(r.request_id) for r in environment_requests)
        subjects.update(str(c.consumer_request_id) for c in consumer_requests)
        events_by_id: dict[UUID, AuditEvent] = {}
        for subject in subjects:
            for event in self.audit.list_events(subject=subject, limit=1000):
                events_by_id[event.event_id] = event
        audit_trail = sorted(events_by_id.values(), key=lambda e: e.occurred_at, reverse=True)

        package = AuditEvidencePackage(
            package_id=uuid4(),
            generated_at=_now(),
            generated_by=generated_by,
            dataset_version_id=version.version_id,
            dataset_name=version.dataset_name,
            version_number=version.version_number,
            dataset_manifest=version,
            environment_requests=environment_requests,
            consumer_requests=consumer_requests,
            classification_summary=classification_summary,
            masking_policy_version=masking_policy_version,
            masking_policy_approvals=masking_policy_approvals,
            certification_report=certification_report,
            subset_manifest=subset_manifest,
            integrity_report=integrity_report,
            quality_report=quality_report,
            refresh_history=refresh_history,
            rollback_history=rollback_history,
            revocation=revocation,
            audit_trail=audit_trail,
            lineage=lineage,
            provenance_notes=provenance_notes,
        )
        # Phase 18A (resolves `docs/problems/problems_final_review.md` P1-7): this was
        # a plain, UNKEYED `hashlib.sha256` digest before this phase --
        # anyone with database write access alone (no key needed) could
        # regenerate a self-consistent checksum after editing the
        # underlying rows. It is now a keyed HMAC-SHA256
        # (`control_plane.platform.evidence_signing`), matching
        # `data_plane.certification.signing`'s guarantee for a
        # `CertificationReport` exactly. See
        # `docs/TAMPER_EVIDENCE_LIMITATIONS.md` for the one, honest,
        # residual limitation neither mechanism solves (both are
        # detection, not prevention, and both are only as strong as
        # their key's secrecy).
        signing_key = evidence_signing.resolve_signing_key()
        package = package.model_copy(
            update={
                "bundle_checksum": compute_bundle_checksum(package, signing_key),
                "bundle_checksum_algorithm": "hmac-sha256",
            }
        )

        self.audit.record(
            event_type=AuditEventType.EVIDENCE_PACKAGE_GENERATED,
            actor=generated_by,
            subject=str(version.version_id),
            outcome="allowed",
            detail={"package_id": str(package.package_id)},
        )
        return package


__all__ = ["EvidenceRepository", "compute_bundle_checksum", "verify_bundle_checksum"]
