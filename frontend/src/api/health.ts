import { apiGet } from "./client";
import type { HealthResponse } from "./types";

/** `GET /api/v1/health` -- liveness only (see `api/v1/health.py`); does
 * not check downstream dependencies. Backs the Platform Health page
 * until Phase 11 adds real readiness/dependency checks. */
export function getHealth(): Promise<HealthResponse> {
  return apiGet<HealthResponse>("/api/v1/health");
}
