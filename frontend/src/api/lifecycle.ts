import { apiGet, apiPost } from "./client";
import type {
  DatasetVersion,
  DatasetVersionStatus,
  Environment,
  EnvironmentDatasetRequest,
  RefreshPolicy,
  RefreshRunRecord,
  RefreshTrigger,
  RollbackRecord,
  SchedulerRunResult,
} from "./types";

/** `GET /api/v1/lifecycle/dataset-versions` (Phase 7). Backs the
 * Datasets list and Dataset Detail pages. */
export function listDatasetVersions(filters: {
  dataset_name?: string;
  status?: DatasetVersionStatus;
} = {}): Promise<DatasetVersion[]> {
  return apiGet<DatasetVersion[]>("/api/v1/lifecycle/dataset-versions", { ...filters });
}

export function getDatasetVersion(versionId: string): Promise<DatasetVersion> {
  return apiGet<DatasetVersion>(`/api/v1/lifecycle/dataset-versions/${versionId}`);
}

export function revokeDatasetVersion(
  versionId: string,
  body: { reason: string; revoked_by: string },
): Promise<DatasetVersion> {
  return apiPost<DatasetVersion>(`/api/v1/lifecycle/dataset-versions/${versionId}/revoke`, body);
}

/** `GET /api/v1/lifecycle/refresh-policies`. Backs the Refresh Calendar page. */
export function listRefreshPolicies(environment?: Environment): Promise<RefreshPolicy[]> {
  return apiGet<RefreshPolicy[]>("/api/v1/lifecycle/refresh-policies", { environment });
}

export function getDefaultRefreshPolicy(environment: Environment): Promise<RefreshPolicy> {
  return apiGet<RefreshPolicy>(`/api/v1/lifecycle/refresh-policies/${environment}/default`);
}

/** `GET /api/v1/lifecycle/environment-requests`. Backs Environment
 * Provisioning and the Refresh Calendar. */
export function listEnvironmentRequests(filters: {
  environment?: Environment;
  dataset_name?: string;
} = {}): Promise<EnvironmentDatasetRequest[]> {
  return apiGet<EnvironmentDatasetRequest[]>("/api/v1/lifecycle/environment-requests", { ...filters });
}

export function getEnvironmentRequest(requestId: string): Promise<EnvironmentDatasetRequest> {
  return apiGet<EnvironmentDatasetRequest>(`/api/v1/lifecycle/environment-requests/${requestId}`);
}

export function refreshEnvironmentRequest(
  requestId: string,
  body: { triggered_by: string; trigger?: RefreshTrigger },
): Promise<RefreshRunRecord> {
  return apiPost<RefreshRunRecord>(`/api/v1/lifecycle/environment-requests/${requestId}/refresh`, body);
}

export function rollbackEnvironmentRequest(
  requestId: string,
  body: { to_version_number: number; performed_by: string; reason: string },
): Promise<RollbackRecord> {
  return apiPost<RollbackRecord>(`/api/v1/lifecycle/environment-requests/${requestId}/rollback`, body);
}

/** `GET /api/v1/lifecycle/scheduler/due` -- what needs refreshing right
 * now. Backs the Refresh Calendar's "due now" view. */
export function listDueRefreshes(asOf?: string): Promise<EnvironmentDatasetRequest[]> {
  return apiGet<EnvironmentDatasetRequest[]>("/api/v1/lifecycle/scheduler/due", { as_of: asOf });
}

export function runDueRefreshes(asOf?: string, triggeredBy = "console-operator"): Promise<SchedulerRunResult> {
  return apiPost<SchedulerRunResult>("/api/v1/lifecycle/scheduler/run-due", undefined, {
    as_of: asOf,
    triggered_by: triggeredBy,
  });
}
