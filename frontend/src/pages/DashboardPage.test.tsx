import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import { DashboardPage } from "./DashboardPage";

const listDatasetVersions = vi.fn();
const listEnvironmentRequests = vi.fn();
const getCatalogSummary = vi.fn();
const listMaskingRuns = vi.fn();
const listCertificationReports = vi.fn();
const getCapacityPlan = vi.fn();

vi.mock("@/api", () => ({
  lifecycleApi: {
    listDatasetVersions: (...args: unknown[]) => listDatasetVersions(...args),
    listEnvironmentRequests: (...args: unknown[]) => listEnvironmentRequests(...args),
  },
  catalogApi: {
    getCatalogSummary: (...args: unknown[]) => getCatalogSummary(...args),
  },
  maskingApi: {
    listMaskingRuns: (...args: unknown[]) => listMaskingRuns(...args),
  },
  certificationApi: {
    listCertificationReports: (...args: unknown[]) => listCertificationReports(...args),
  },
  capacityApi: {
    getCapacityPlan: (...args: unknown[]) => getCapacityPlan(...args),
  },
}));

function renderDashboard() {
  return render(
    <MemoryRouter>
      <DashboardPage />
    </MemoryRouter>,
  );
}

describe("DashboardPage", () => {
  it("renders real data returned by the API client, not fabricated numbers", async () => {
    listDatasetVersions.mockResolvedValue([
      { version_id: "v1", status: "active" },
      { version_id: "v2", status: "revoked" },
    ]);
    listEnvironmentRequests.mockResolvedValue([]);
    getCatalogSummary.mockResolvedValue({
      total_columns: 42,
      total_datasets: 6,
      by_category: { phi: 10, pii: 5 },
      needs_review: 3,
    });
    listMaskingRuns.mockResolvedValue([]);
    listCertificationReports.mockResolvedValue([]);
    getCapacityPlan.mockResolvedValue({
      generated_at: "2026-01-01T00:00:00Z",
      dataset_name: null,
      dataset_version_footprints: [],
      environment_demands: [],
      environment_count: 0,
      distinct_dataset_version_count: 0,
      naive_total_storage_bytes: 4000,
      shared_total_storage_bytes: 3000,
      storage_savings_bytes: 1000,
      storage_savings_pct: 0.25,
    });

    renderDashboard();

    // Dataset-by-status tile reflects the mocked API response.
    await waitFor(() => expect(screen.getByText("Active")).toBeInTheDocument());
    expect(screen.getByText("Revoked")).toBeInTheDocument();

    // Catalog summary tile.
    expect(await screen.findByText("42")).toBeInTheDocument();
    expect(screen.getByText("Needing steward review")).toBeInTheDocument();

    // Storage footprint tile: real formatted bytes, not invented text.
    expect(await screen.findByText("3.00 KB")).toBeInTheDocument();
    expect(screen.getByText("25.0%")).toBeInTheDocument();
  });

  it("shows an honest error state for a section whose API call fails, without blocking the rest of the dashboard", async () => {
    listDatasetVersions.mockRejectedValue(new Error("simulated failure"));
    listEnvironmentRequests.mockResolvedValue([]);
    getCatalogSummary.mockResolvedValue({ total_columns: 1, total_datasets: 1, by_category: {}, needs_review: 0 });
    listMaskingRuns.mockResolvedValue([]);
    listCertificationReports.mockResolvedValue([]);
    getCapacityPlan.mockResolvedValue({
      generated_at: "2026-01-01T00:00:00Z",
      dataset_name: null,
      dataset_version_footprints: [],
      environment_demands: [],
      environment_count: 0,
      distinct_dataset_version_count: 0,
      naive_total_storage_bytes: 0,
      shared_total_storage_bytes: 0,
      storage_savings_bytes: 0,
      storage_savings_pct: 0,
    });

    renderDashboard();

    expect(await screen.findByText("simulated failure")).toBeInTheDocument();
    // The catalog section still renders real data despite the other section's failure.
    expect(await screen.findByText("Datasets cataloged")).toBeInTheDocument();
  });
});
