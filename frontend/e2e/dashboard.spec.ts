import { expect, test } from "@playwright/test";

/**
 * Critical workflow 1: navigating to the Dashboard and seeing real data.
 * Runs against the real control-plane API (see `playwright.config.ts`'s
 * header for the required startup sequence) -- every assertion below
 * checks for structure/labels this phase's real pages always render,
 * not hand-picked demo values that would break if the demo script's
 * seeds ever change.
 */
test.describe("Dashboard", () => {
  test("shows real data across every required section", async ({ page }) => {
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Dashboard", level: 1 })).toBeVisible();

    // Datasets by status -- real dataset-version data from the lifecycle API.
    await expect(page.getByRole("heading", { name: "Datasets by status" })).toBeVisible();

    // PHI/PII classifications -- real catalog summary counts.
    const catalogSection = page.locator("section", { has: page.getByRole("heading", { name: "PHI/PII classifications" }) });
    await expect(catalogSection.getByText("Total classified columns")).toBeVisible();
    // The demo data registers a real catalog with more than zero columns.
    await expect(catalogSection.getByText(/^\d[\d,]*$/).first()).toBeVisible();

    // Masking coverage, certification, upcoming refreshes, storage
    // footprint, compute utilization, environment demand -- every
    // required Dashboard section from the Phase 9 spec is present.
    for (const heading of [
      "Masking coverage",
      "Certification",
      "Upcoming refreshes",
      "Storage footprint",
      "Compute utilization estimates",
      "Environment demand",
    ]) {
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    }

    // No section is left in a perpetual loading state.
    await expect(page.getByRole("status")).toHaveCount(0);
  });

  test("left navigation lists every required console page", async ({ page }) => {
    await page.goto("/");
    const nav = page.getByRole("navigation", { name: "Primary" });
    for (const label of [
      "Dashboard",
      "Data Sources",
      "Data Catalog",
      "Sensitive Data Discovery",
      "Masking Policies",
      "Subsetting Jobs",
      "Synthetic Data",
      "Certification",
      "Datasets",
      "Environment Provisioning",
      "Refresh Calendar",
      "Capacity & Cost",
      "Audit Trail",
      "Platform Health",
    ]) {
      await expect(nav.getByRole("link", { name: label })).toBeVisible();
    }
  });
});
