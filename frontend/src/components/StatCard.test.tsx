import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatCard } from "./StatCard";

describe("StatCard", () => {
  it("renders the label/value pair as a definition list term/definition", () => {
    render(<StatCard label="Total datasets" value={42} />);
    expect(screen.getByText("Total datasets")).toBeInTheDocument();
    expect(screen.getByText("42")).toBeInTheDocument();
  });

  it("renders optional detail text", () => {
    render(<StatCard label="Savings" value="83.4%" detail="1.2 TB reclaimed" />);
    expect(screen.getByText("1.2 TB reclaimed")).toBeInTheDocument();
  });

  it("applies the tone class for coloring critical values", () => {
    const { container } = render(<StatCard label="Failures" value={3} tone="critical" />);
    expect(container.querySelector(".stat-card--critical")).not.toBeNull();
  });
});
