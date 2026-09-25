import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import type { ApiDataState } from "@/hooks/useApiData";
import { AsyncSection } from "./AsyncSection";

function state<T>(overrides: Partial<ApiDataState<T>>): ApiDataState<T> {
  return { data: null, loading: false, error: null, reload: () => {}, ...overrides };
}

describe("AsyncSection", () => {
  it("renders a loading indicator while loading", () => {
    render(
      <AsyncSection state={state<number>({ loading: true })} loadingLabel="Loading things">
        {() => <p>never rendered</p>}
      </AsyncSection>,
    );
    expect(screen.getByRole("status")).toBeInTheDocument();
  });

  it("renders an error state when the fetch failed", () => {
    render(
      <AsyncSection state={state<number>({ error: new Error("network down") })}>
        {() => <p>never rendered</p>}
      </AsyncSection>,
    );
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.getByText("network down")).toBeInTheDocument();
  });

  it("renders children with the real data once loaded successfully", () => {
    render(
      <AsyncSection state={state<{ label: string }>({ data: { label: "real data" } })}>
        {(data) => <p>{data.label}</p>}
      </AsyncSection>,
    );
    expect(screen.getByText("real data")).toBeInTheDocument();
  });
});
