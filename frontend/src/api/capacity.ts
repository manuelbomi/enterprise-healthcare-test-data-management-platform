import { apiGet, apiPost } from "./client";
import type {
  CapacityPlan,
  DatasetVersionFootprint,
  EnvironmentCapacityDemand,
  IllustrativeCapacityPlan,
  IllustrativeCapacityScenario,
  VacuumCandidate,
} from "./types";

/** `GET /api/v1/capacity/dataset-versions/{id}/footprint` (Phase 8). */
export function getDatasetVersionFootprint(versionId: string): Promise<DatasetVersionFootprint> {
  return apiGet<DatasetVersionFootprint>(`/api/v1/capacity/dataset-versions/${versionId}/footprint`);
}

/** `GET /api/v1/capacity/environment-requests/{id}/demand`. */
export function getEnvironmentCapacityDemand(requestId: string): Promise<EnvironmentCapacityDemand> {
  return apiGet<EnvironmentCapacityDemand>(`/api/v1/capacity/environment-requests/${requestId}/demand`);
}

/** `GET /api/v1/capacity/plan` -- the real, DB-backed naive-vs-shared
 * storage comparison. Backs the Capacity & Cost page and Dashboard
 * storage-footprint tile. */
export function getCapacityPlan(datasetName?: string): Promise<CapacityPlan> {
  return apiGet<CapacityPlan>("/api/v1/capacity/plan", { dataset_name: datasetName });
}

/** `GET /api/v1/capacity/vacuum-candidates`. */
export function getVacuumCandidates(datasetName?: string): Promise<VacuumCandidate[]> {
  return apiGet<VacuumCandidate[]>("/api/v1/capacity/vacuum-candidates", { dataset_name: datasetName });
}

/** `GET /api/v1/capacity/illustrative-plan` -- pure calculation, no
 * database access; explicitly labeled illustrative/modeled, never a
 * measurement (see `docs/CAPACITY_COST_TRADEOFFS.md`). */
export function getIllustrativeCapacityPlan(productionBaselineTb = 100): Promise<IllustrativeCapacityPlan> {
  return apiGet<IllustrativeCapacityPlan>("/api/v1/capacity/illustrative-plan", {
    production_baseline_tb: productionBaselineTb,
  });
}

export function postIllustrativeCapacityPlan(
  scenario: IllustrativeCapacityScenario,
): Promise<IllustrativeCapacityPlan> {
  return apiPost<IllustrativeCapacityPlan>("/api/v1/capacity/illustrative-plan", scenario);
}
