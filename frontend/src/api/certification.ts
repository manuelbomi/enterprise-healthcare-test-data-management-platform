import { apiGet } from "./client";
import type { CertificationReportRecord } from "./types";

/** `GET /api/v1/certification/reports` (Phase 9) -- real
 * `certification_report.json` artifacts Phase 6's certification
 * pipeline wrote, including its enforced status lifecycle and gate
 * results. Backs the Certification page and the Dataset Detail page's
 * certification evidence section. */
export function listCertificationReports(): Promise<CertificationReportRecord[]> {
  return apiGet<CertificationReportRecord[]>("/api/v1/certification/reports");
}

/** `GET /api/v1/certification/reports/{report_id}` -- used by the
 * Dataset Detail page to resolve `DatasetVersion.certification_report_id`. */
export function getCertificationReport(reportId: string): Promise<CertificationReportRecord> {
  return apiGet<CertificationReportRecord>(`/api/v1/certification/reports/${reportId}`);
}
