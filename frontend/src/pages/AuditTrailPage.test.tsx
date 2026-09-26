import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { AuditTrailPage } from "./AuditTrailPage";

const listAuditEvents = vi.fn();

vi.mock("@/api", () => ({
  auditApi: {
    listAuditEvents: (...args: unknown[]) => listAuditEvents(...args),
  },
}));

describe("AuditTrailPage", () => {
  it("renders real audit events returned by GET /api/v1/audit/events, not a placeholder", async () => {
    // Phase 18A fix (docs/problems/problems_final_review.md P1-4): this page used to
    // claim "there is no backing API for this page to call" -- false
    // since Phase 11. This test proves the real endpoint is now called
    // and its real data rendered.
    listAuditEvents.mockResolvedValue([
      {
        event_id: "11111111-1111-1111-1111-111111111111",
        event_type: "dataset_version_revoked",
        actor: "security@example.org",
        subject: "22222222-2222-2222-2222-222222222222",
        outcome: "allowed",
        detail: { reason: "policy defect" },
        occurred_at: "2026-01-01T00:00:00Z",
      },
    ]);

    render(<AuditTrailPage />);

    await waitFor(() => expect(listAuditEvents).toHaveBeenCalled());
    expect(await screen.findByText("security@example.org")).toBeInTheDocument();
    expect(screen.getByRole("table")).toBeInTheDocument();
    expect(screen.queryByText("Audit trail is not implemented yet")).not.toBeInTheDocument();
    expect(screen.queryByText(/there is no backing API/)).not.toBeInTheDocument();
  });

  it("renders an honest empty state when there are no audit events yet", async () => {
    listAuditEvents.mockResolvedValue([]);
    render(<AuditTrailPage />);
    expect(await screen.findByText(/No audit events match/)).toBeInTheDocument();
  });
});
