import { apiGet } from "./client";
import type { SyntheticManifestRecord } from "./types";

/** `GET /api/v1/synthetic/manifests` (Phase 9) -- real
 * `synthetic_generation_manifest.json` artifacts Phase 5's scenario
 * generator wrote. Backs the Synthetic Data page. */
export function listSyntheticManifests(): Promise<SyntheticManifestRecord[]> {
  return apiGet<SyntheticManifestRecord[]>("/api/v1/synthetic/manifests");
}

/** `GET /api/v1/synthetic/manifests/{manifest_id}`. */
export function getSyntheticManifest(manifestId: string): Promise<SyntheticManifestRecord> {
  return apiGet<SyntheticManifestRecord>(`/api/v1/synthetic/manifests/${manifestId}`);
}
