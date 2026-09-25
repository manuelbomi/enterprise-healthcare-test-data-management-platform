import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ApiError } from "@/api/client";
import { ErrorState } from "./ErrorState";

describe("ErrorState", () => {
  it("labels a 503 ApiError as 'Not available yet' (the platform's well-known artifact-not-generated condition)", () => {
    render(<ErrorState error={new ApiError(503, "Catalog artifact not found at 'catalog.json'.")} />);
    expect(screen.getByText("Not available yet")).toBeInTheDocument();
    expect(screen.getByText(/Catalog artifact not found/)).toBeInTheDocument();
  });

  it("labels a 404 ApiError as 'Not found'", () => {
    render(<ErrorState error={new ApiError(404, "No catalog entry for x/y/z.")} />);
    expect(screen.getByText("Not found")).toBeInTheDocument();
  });

  it("labels a plain (non-ApiError) failure generically, without inventing a status", () => {
    render(<ErrorState error={new Error("Network failure")} />);
    expect(screen.getByText("Something went wrong loading this data")).toBeInTheDocument();
    expect(screen.getByText("Network failure")).toBeInTheDocument();
  });

  it("invokes onRetry when the retry button is clicked", () => {
    const onRetry = vi.fn();
    render(<ErrorState error={new Error("boom")} onRetry={onRetry} />);
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("renders as an alert region for assistive technology", () => {
    render(<ErrorState error={new Error("boom")} />);
    expect(screen.getByRole("alert")).toBeInTheDocument();
  });
});
