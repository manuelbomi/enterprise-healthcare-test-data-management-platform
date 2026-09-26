import { useState } from "react";
import { auditApi } from "@/api";
import type { AuditEvent } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useApiData } from "@/hooks/useApiData";
import { formatDate, titleCase } from "@/lib/format";

/**
 * Audit Trail page -- real, DB-backed, calling `GET /api/v1/audit/events`
 * (`control_plane.platform.audit.AuditLogRepository`, Phase 11).
 *
 * **Phase 18A fix** (`problems_final_review.md` P1-4): before this
 * phase, this page rendered a placeholder claiming "there is no backing
 * API for this page to call" -- true when written in Phase 9, but false
 * since Phase 11 shipped this exact endpoint two phases later. Nobody
 * came back to update this page. This is the fix: a real, minimal,
 * filterable table over the real audit log, following the same
 * `useApiData`/`AsyncSection`/`DataTable` pattern every other read-only
 * page in this console already uses (see `CertificationPage.tsx`).
 *
 * `actor`/`subject`/`event_type` are unverified free text everywhere
 * they are written (see `control_plane.platform.rbac`'s module
 * docstring and `problems_final_review.md` P2-13) -- this page does not
 * claim otherwise; it displays the real audit log, not a stronger
 * guarantee than the log itself carries.
 */
export function AuditTrailPage() {
  const [subjectFilter, setSubjectFilter] = useState("");
  const [actorFilter, setActorFilter] = useState("");

  const events = useApiData(
    () =>
      auditApi.listAuditEvents({
        subject: subjectFilter.trim() || undefined,
        actor: actorFilter.trim() || undefined,
      }),
    [subjectFilter, actorFilter],
  );

  return (
    <>
      <PageHeader
        title="Audit Trail"
        description="The real, immutable audit event log (Phase 11) -- every recorded lifecycle/governance mutation, access, and RBAC denial. Actor/subject fields are self-reported, unverified free text, not a security control (see SECURITY.md)."
      />
      <form
        className="filter-bar"
        onSubmit={(event) => event.preventDefault()}
        aria-label="Filter audit events"
      >
        <label>
          Subject (e.g. a dataset version id)
          <input
            type="text"
            value={subjectFilter}
            onChange={(event) => setSubjectFilter(event.target.value)}
            placeholder="Filter by subject"
          />
        </label>
        <label>
          Actor
          <input
            type="text"
            value={actorFilter}
            onChange={(event) => setActorFilter(event.target.value)}
            placeholder="Filter by actor"
          />
        </label>
      </form>
      <AsyncSection state={events} loadingLabel="Loading audit events">
        {(rows) => (
          <DataTable<AuditEvent>
            caption={`${rows.length} audit event(s)`}
            getRowKey={(row) => row.event_id}
            rows={rows}
            emptyMessage="No audit events match the current filter."
            columns={columns}
          />
        )}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<AuditEvent>[] = [
  { key: "occurred_at", header: "When", render: (row) => formatDate(row.occurred_at) },
  { key: "event_type", header: "Event", render: (row) => titleCase(row.event_type) },
  { key: "actor", header: "Actor", render: (row) => row.actor },
  { key: "subject", header: "Subject", render: (row) => row.subject },
  {
    key: "outcome",
    header: "Outcome",
    render: (row) => (
      <span className={`badge badge--${row.outcome === "denied" || row.outcome === "failed" ? "critical" : "good"}`}>
        {row.outcome}
      </span>
    ),
  },
];
