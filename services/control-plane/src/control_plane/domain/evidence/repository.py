"""`EvidenceRepository` -- builds a Phase 13 `AuditEvidencePackage` for
one dataset version.

This is a *read-mostly* aggregator, not a new source of truth: every
substantive field it fills in is a real re-export of an already-real
Phase 2/6/7/10/11 artifact --

- the dataset manifest and provisioning/refresh/rollback/revocation
  history come from `control_plane.domain.lifecycle.LifecycleRepository`
  (Phase 7, extended this phase with `list_refresh_runs`/
  `list_rollback_events` -- see `problems_phase_13.md`);
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
  module docstring and `problems_phase_13.md` P13-1).

The one genuinely new piece of business logic here is the aggregation
itself (which rows to pull for a given dataset version, how to merge
several `AuditEvent` queries into one deduplicated, time-ordered trail)
and the bundle checksum. See `docs/adr/0016-audit-evidence-lives-in-
control-plane.md` for why this lives in `services/control-plane` rather
than `services/governance-service`, mirroring ADR-0014/0015's reasoning.
"""

from __future__ import annotations

import hashlib
import json
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
from control_plane.platform.audit import AuditLogRepository

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
        package = package.model_copy(update={"bundle_checksum": compute_bundle_checksum(package)})

        self.audit.record(
            event_type=AuditEventType.EVIDENCE_PACKAGE_GENERATED,
            actor=generated_by,
            subject=str(version.version_id),
            outcome="allowed",
            detail={"package_id": str(package.package_id)},
        )
        return package


def _canonical_payload(package: AuditEvidencePackage) -> bytes:
    """The exact byte sequence `bundle_checksum` is computed over: every
    field except `bundle_checksum` itself (checksumming a field that
    includes itself is circular), serialized the same
    `sort_keys=True, separators=(",", ":")` way
    `data_plane.certification.signing._canonical_payload` uses for
    `CertificationReport.integrity_signature` -- so re-checksumming the
    same content always produces the same digest."""

    payload = package.model_dump(mode="json", exclude={"bundle_checksum"})
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def compute_bundle_checksum(package: AuditEvidencePackage) -> str:
    """SHA-256 hex digest over `package`'s canonical JSON (excluding
    `bundle_checksum` itself). See `problems_phase_13.md` P13-2 for why
    this is an integrity check, not a cryptographic non-repudiation
    signature (it uses no secret key, unlike
    `data_plane.certification.signing`'s HMAC over `CertificationReport`)."""

    return hashlib.sha256(_canonical_payload(package)).hexdigest()


def verify_bundle_checksum(package: AuditEvidencePackage) -> bool:
    """True iff `package.bundle_checksum` matches a freshly recomputed
    checksum over its current fields -- i.e. the package has not been
    modified since it was generated."""

    if not package.bundle_checksum:
        return False
    return compute_bundle_checksum(package) == package.bundle_checksum


__all__ = ["EvidenceRepository", "compute_bundle_checksum", "verify_bundle_checksum"]
