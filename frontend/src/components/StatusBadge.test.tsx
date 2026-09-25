import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { BooleanBadge, StatusBadge } from "./StatusBadge";

describe("StatusBadge", () => {
  it("title-cases the raw status value", () => {
    render(<StatusBadge status="rolled_back" />);
    expect(screen.getByText("Rolled Back")).toBeInTheDocument();
  });

  it("renders a known good status (certified/published/active/passed)", () => {
    render(<StatusBadge status="certified" />);
    const badge = screen.getByText("Certified");
    expect(badge.className).toContain("badge--good");
  });

  it("renders a known critical status (failed/revoked)", () => {
    render(<StatusBadge status="failed" />);
    const badge = screen.getByText("Failed");
    expect(badge.className).toContain("badge--critical");
  });

  it("falls back to neutral tone for an unrecognized status rather than guessing", () => {
    render(<StatusBadge status="something_unmapped" />);
    const badge = screen.getByText("Something Unmapped");
    expect(badge.className).toContain("badge--neutral");
  });
});

describe("BooleanBadge", () => {
  it("renders the true label with a good tone", () => {
    render(<BooleanBadge value={true} trueLabel="Passed" falseLabel="Failed" />);
    const badge = screen.getByText("Passed");
    expect(badge.className).toContain("badge--good");
  });

  it("renders the false label with a critical tone", () => {
    render(<BooleanBadge value={false} trueLabel="Passed" falseLabel="Failed" />);
    const badge = screen.getByText("Failed");
    expect(badge.className).toContain("badge--critical");
  });
});
