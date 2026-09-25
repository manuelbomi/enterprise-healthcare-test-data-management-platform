import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NotYetAvailable } from "./NotYetAvailable";

describe("NotYetAvailable", () => {
  it("renders the title, reason, and roadmap pointer honestly (no fabricated data)", () => {
    render(
      <NotYetAvailable
        title="Audit trail is not implemented yet"
        reason="No backing API exists yet."
        roadmapPhase="Phase 13 (Auditability and compliance evidence)"
      />,
    );
    expect(screen.getByRole("heading", { name: "Audit trail is not implemented yet" })).toBeInTheDocument();
    expect(screen.getByText("No backing API exists yet.")).toBeInTheDocument();
    expect(screen.getByText(/Phase 13/)).toBeInTheDocument();
  });

  it("omits the roadmap pointer when none is given", () => {
    render(<NotYetAvailable title="Not available" reason="reason text" />);
    expect(screen.queryByText(/ROADMAP\.md/)).not.toBeInTheDocument();
  });
});
