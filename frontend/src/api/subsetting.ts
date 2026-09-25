import { apiGet } from "./client";
import type { SubsetManifestRecord } from "./types";

/** `GET /api/v1/subsetting/manifests` (Phase 9) -- real
 * `subset_manifest.json` artifacts Phase 4's subsetting engine wrote.
 * Backs the Subsetting Jobs page. */
export function listSubsetManifests(): Promise<SubsetManifestRecord[]> {
  return apiGet<SubsetManifestRecord[]>("/api/v1/subsetting/manifests");
}

/** `GET /api/v1/subsetting/manifests/{manifest_id}`. */
export function getSubsetManifest(manifestId: string): Promise<SubsetManifestRecord> {
  return apiGet<SubsetManifestRecord>(`/api/v1/subsetting/manifests/${manifestId}`);
}
