import { apiPost } from "./client";
import type { AuditEvidencePackage, CertificationReport, SubsetManifest } from "./types";

/**
 * `POST /api/v1/evidence/dataset-versions/{version_id}/package` (Phase
 * 13) -- aggregates every real artifact the control plane holds about
 * a dataset version into one checksum-verified `AuditEvidencePackage`.
 * Added in Phase 18A (`docs/problems/problems_final_review.md` P1-4): before this
 * phase, no frontend code called this endpoint at all.
 *
 * `certification_report`/`subset_manifest` are optional -- see
 * `docs/COMPLIANCE_EVIDENCE.md`: the control plane does not durably
 * store either, so they are only embedded if the caller supplies them.
 */
export function generateEvidencePackage(
  versionId: string,
  body: {
    generated_by: string;
    certification_report?: CertificationReport;
    subset_manifest?: SubsetManifest;
  },
): Promise<AuditEvidencePackage> {
  return apiPost<AuditEvidencePackage>(`/api/v1/evidence/dataset-versions/${versionId}/package`, body);
}
