import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { PlatformHealthPage } from "./PlatformHealthPage";

const getHealth = vi.fn();

vi.mock("@/api", () => ({
  healthApi: {
    getHealth: (...args: unknown[]) => getHealth(...args),
  },
}));

describe("PlatformHealthPage", () => {
  it("renders the real health endpoint's status and service name", async () => {
    getHealth.mockResolvedValue({ status: "ok", service: "control-plane" });
    render(<PlatformHealthPage />);

    expect(await screen.findByText("control-plane")).toBeInTheDocument();
    expect(screen.getByText("ok")).toBeInTheDocument();
  });

  it("surfaces a real failure instead of silently showing 'ok'", async () => {
    getHealth.mockRejectedValue(new Error("connection refused"));
    render(<PlatformHealthPage />);

    expect(await screen.findByText("connection refused")).toBeInTheDocument();
  });
});
