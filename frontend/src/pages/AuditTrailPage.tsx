import { NotYetAvailable } from "@/components/NotYetAvailable";
import { PageHeader } from "@/components/PageHeader";

/**
 * Audit Trail is explicitly a later phase (`ROADMAP.md` Phase 13,
 * "Auditability and compliance evidence") -- there is no
 * security/governance-plane immutable audit event log yet
 * (`ARCHITECTURE.md` section 2.4 describes it as a design target, not
 * built). Per the Phase 9 instructions, this is an honest placeholder,
 * not a gap papered over with fabricated audit entries.
 */
export function AuditTrailPage() {
  return (
    <>
      <PageHeader title="Audit Trail" />
      <NotYetAvailable
        title="Audit trail is not implemented yet"
        reason="The security/governance plane's immutable audit event log (ARCHITECTURE.md section 2.4) does not exist yet -- there is no backing API for this page to call, and this page deliberately does not fabricate audit entries to fill the space."
        roadmapPhase="Phase 13 (Auditability and compliance evidence)"
      />
    </>
  );
}
