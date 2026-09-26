import { apiGet } from "./client";
import type { AuditEvent, AuditEventType } from "./types";

/**
 * `GET /api/v1/audit/events` (Phase 11) -- the real, DB-backed
 * immutable audit event log `AuditTrailPage` used to (falsely, as of
 * Phase 11) claim had no backing API. Added in Phase 18A
 * (`docs/problems/problems_final_review.md` P1-4): before this phase, no frontend
 * code called this endpoint at all despite it having existed since
 * Phase 11.
 */
export function listAuditEvents(
  filters: {
    event_type?: AuditEventType;
    subject?: string;
    actor?: string;
    limit?: number;
  } = {},
): Promise<AuditEvent[]> {
  return apiGet<AuditEvent[]>("/api/v1/audit/events", { ...filters });
}
