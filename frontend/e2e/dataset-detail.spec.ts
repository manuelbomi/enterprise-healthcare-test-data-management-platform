import { expect, test } from "@playwright/test";

/**
 * Critical workflow 3: viewing a Dataset Detail page and seeing its
 * composed real data -- lineage, masking policy, subset policy,
 * certification, row counts, referential-integrity status, storage
 * footprint, and consumer environments (see
 * `src/pages/DatasetDetailPage.tsx`'s module docstring for exactly
 * which of the four real endpoints each section comes from). Runs
 * against the real control-plane API; navigates via the real Datasets
 * list rather than hard-coding a dataset-version id, so it keeps
 * working across different demo-data runs.
 */
test.describe("Dataset Detail", () => {
  test("navigating from the Datasets list shows the full composed detail view", async ({ page }) => {
    await page.goto("/datasets");
    await expect(page.getByRole("heading", { name: "Datasets", level: 1 })).toBeVisible();

    const table = page.getByRole("table");
    await expect(table).toBeVisible();
    const firstRowLink = table.locator("tbody tr").first().getByRole("link").first();
    const datasetName = (await firstRowLink.textContent())?.trim();
    expect(datasetName).toBeTruthy();

    await firstRowLink.click();
    await expect(page).toHaveURL(/\/datasets\/[0-9a-f-]+/);

    // Every required Dataset Detail section from the Phase 9 spec.
    for (const heading of [
      "Dataset version",
      "Row counts",
      "Masking policy",
      "Subset policy",
      "Certification",
      "Storage footprint",
      "Consumer environments",
      "Source systems",
      "Lineage",
    ]) {
      await expect(page.getByRole("heading", { name: heading })).toBeVisible();
    }

    // Referential-integrity status is surfaced inside the Certification
    // section, derived from the real certification report's gate result.
    await expect(page.getByText("Referential-integrity status")).toBeVisible();
  });
});
