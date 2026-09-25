import { apiGet } from "./client";
import type { CatalogDatasetRow, CatalogEntry, CatalogSummary, ClassificationTier, SensitivityCategory } from "./types";

export interface CatalogEntryFilters {
  source_system?: string;
  dataset?: string;
  category?: SensitivityCategory;
  tier?: ClassificationTier;
  needs_review?: boolean;
}

/** `GET /api/v1/catalog` -- the PHI/PII data catalog (Phase 2), read
 * from the JSON artifact `data_plane.discovery` produced (ADR-0009).
 * Backs the Data Catalog and Sensitive Data Discovery pages. */
export function listCatalogEntries(filters: CatalogEntryFilters = {}): Promise<CatalogEntry[]> {
  return apiGet<CatalogEntry[]>("/api/v1/catalog", { ...filters });
}

/** `GET /api/v1/catalog/summary`. */
export function getCatalogSummary(): Promise<CatalogSummary> {
  return apiGet<CatalogSummary>("/api/v1/catalog/summary");
}

/** `GET /api/v1/catalog/datasets` -- one row per (source_system, dataset). */
export function listCatalogDatasets(): Promise<CatalogDatasetRow[]> {
  return apiGet<CatalogDatasetRow[]>("/api/v1/catalog/datasets");
}

/** `GET /api/v1/catalog/{source_system}/{dataset}/{column}`. */
export function getCatalogEntry(sourceSystem: string, dataset: string, column: string): Promise<CatalogEntry> {
  return apiGet<CatalogEntry>(
    `/api/v1/catalog/${encodeURIComponent(sourceSystem)}/${encodeURIComponent(dataset)}/${encodeURIComponent(column)}`,
  );
}
