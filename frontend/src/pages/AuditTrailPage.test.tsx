import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AuditTrailPage } from "./AuditTrailPage";

describe("AuditTrailPage", () => {
  it("renders an honest not-yet-implemented placeholder pointing at Phase 13, rather than fabricated audit entries", () => {
    render(<AuditTrailPage />);
    expect(screen.getByText("Audit trail is not implemented yet")).toBeInTheDocument();
    expect(screen.getByText(/Phase 13/)).toBeInTheDocument();
    expect(screen.queryByRole("table")).not.toBeInTheDocument();
  });
});
