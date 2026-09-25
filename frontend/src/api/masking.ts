import { apiGet } from "./client";
import type { MaskingRunRecord } from "./types";

/** `GET /api/v1/masking/runs` (Phase 9) -- real
 * `masking_run_summary.json` artifacts Phase 3's masking engine wrote,
 * discovered under the configured artifact root
 * (`TDM_CONTROL_PLANE_MASKING_ARTIFACTS_ROOT`). See
 * `control_plane.artifacts.masking` and `problems_phase_09.md` for why
 * this is a new read-only endpoint rather than a faked policy list. */
export function listMaskingRuns(): Promise<MaskingRunRecord[]> {
  return apiGet<MaskingRunRecord[]>("/api/v1/masking/runs");
}
