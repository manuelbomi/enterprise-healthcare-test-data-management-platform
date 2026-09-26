import { apiGet } from "./client";
import type {
  BusinessConsumer,
  ConsumerDatasetRequest,
  Environment,
  MaskingPolicyVersion,
  PolicyApproval,
  PolicyApprovalStatus,
} from "./types";

/**
 * Read-only client for the Phase 10 centralized masking governance API
 * (`api/v1/governance.py`). Added in Phase 18A
 * (`problems_final_review.md` P1-4): before this phase, no frontend
 * code called any Phase 10 governance endpoint at all, and this module
 * did not exist. Deliberately read-only for now -- there is still no
 * governance UI/page consuming these (`problems_final_review.md`
 * P3-5 tracks that separately); this module exists so that gap is a
 * missing *page*, not also a missing *API client*.
 */

export function listPolicyVersions(
  filters: { policy_name?: string; approval_status?: PolicyApprovalStatus } = {},
): Promise<MaskingPolicyVersion[]> {
  return apiGet<MaskingPolicyVersion[]>("/api/v1/governance/policy-versions", { ...filters });
}

export function getPolicyVersion(policyVersionId: string): Promise<MaskingPolicyVersion> {
  return apiGet<MaskingPolicyVersion>(`/api/v1/governance/policy-versions/${policyVersionId}`);
}

export function getApprovedPolicyVersion(policyName: string): Promise<MaskingPolicyVersion> {
  return apiGet<MaskingPolicyVersion>(`/api/v1/governance/policy-versions/approved/${policyName}`);
}

export function listPolicyApprovals(policyVersionId: string): Promise<PolicyApproval[]> {
  return apiGet<PolicyApproval[]>(`/api/v1/governance/policy-versions/${policyVersionId}/approvals`);
}

export function listBusinessConsumers(): Promise<BusinessConsumer[]> {
  return apiGet<BusinessConsumer[]>("/api/v1/governance/business-consumers");
}

export function getBusinessConsumer(businessConsumerId: string): Promise<BusinessConsumer> {
  return apiGet<BusinessConsumer>(`/api/v1/governance/business-consumers/${businessConsumerId}`);
}

export function listConsumerRequests(
  filters: { business_consumer_id?: string; environment?: Environment; dataset_name?: string } = {},
): Promise<ConsumerDatasetRequest[]> {
  return apiGet<ConsumerDatasetRequest[]>("/api/v1/governance/consumer-requests", { ...filters });
}

export function getConsumerRequest(consumerRequestId: string): Promise<ConsumerDatasetRequest> {
  return apiGet<ConsumerDatasetRequest>(`/api/v1/governance/consumer-requests/${consumerRequestId}`);
}
