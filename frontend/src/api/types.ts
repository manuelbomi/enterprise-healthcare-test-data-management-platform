/**
 * TypeScript types mirroring the Pydantic contracts in
 * `libs/contracts/src/healthcare_tdm_contracts/` that the control-plane
 * API (`services/control-plane/src/control_plane/api/v1/`) serves.
 *
 * These are hand-maintained, not generated (see
 * `docs/adr/0008-frontend-stack.md`'s "Consequences": keeping these in
 * sync with the Python contracts is tracked as a Phase 19
 * contract-testing concern). Field names, enum values, and optionality
 * are copied field-for-field from the Python source so a reviewer can
 * diff this file against `libs/contracts` directly. Every FastAPI JSON
 * response uses `datetime`/`UUID` serialized as ISO-8601 strings, so
 * every Python `datetime`/`UUID` field below is typed `string`.
 */

// ---------------------------------------------------------------------
// classification.py
// ---------------------------------------------------------------------

export type ClassificationTier =
  | "direct_identifier"
  | "quasi_identifier"
  | "sensitive_clinical_attribute"
  | "non_sensitive";

export type SensitivityCategory =
  | "direct_identifier"
  | "quasi_identifier"
  | "phi"
  | "pii"
  | "sensitive"
  | "non_sensitive";

export type ClassificationMethod = "schema_based" | "rule_based" | "manual_override";

export interface ColumnClassification {
  source_system: string;
  dataset: string;
  column: string;
  tier: ClassificationTier;
  category: SensitivityCategory | null;
  confidence: number;
  detector: string;
  method: ClassificationMethod;
  reason: string;
  confirmed_by: string | null;
  confirmed_at: string | null;
  updated_at: string;
}

/**
 * `ColumnClassification.needs_review` is a Python `@property`, not a
 * serialized field -- the API never sends it. Recomputed client-side
 * from the same rule (`confirmed_by is None and confidence < 0.7`,
 * `libs/contracts/src/healthcare_tdm_contracts/classification.py`).
 */
export function needsReview(classification: ColumnClassification): boolean {
  return classification.confirmed_by === null && classification.confidence < 0.7;
}

// ---------------------------------------------------------------------
// masking.py (policy-preview vocabulary used by the catalog)
// ---------------------------------------------------------------------

export type MaskingStrategy =
  | "deterministic_tokenization"
  | "generalization"
  | "synthetic_replacement"
  | "passthrough";

export type MaskingTechnique =
  | "redaction"
  | "nullification"
  | "hashing"
  | "hmac_pseudonymization"
  | "tokenization"
  | "format_preserving_synthetic"
  | "date_shift"
  | "email_mask"
  | "phone_mask"
  | "address_replacement"
  | "name_replacement"
  | "passthrough";

// ---------------------------------------------------------------------
// catalog.py
// ---------------------------------------------------------------------

export type RetentionClassification = "ephemeral" | "standard" | "extended" | "persistent_reference";

export interface CatalogEntry {
  classification: ColumnClassification;
  masking_requirement: MaskingStrategy;
  owner: string;
  retention_classification: RetentionClassification;
}

export interface CatalogSummary {
  total_columns: number;
  total_datasets: number;
  by_category: Record<string, number>;
  needs_review: number;
}

export interface CatalogDatasetRow {
  source_system: string;
  dataset: string;
  column_count: number;
  most_severe_category: SensitivityCategory | null;
  owner: string;
}

// ---------------------------------------------------------------------
// lifecycle.py
// ---------------------------------------------------------------------

export type Environment = "dev" | "qa" | "sit" | "uat" | "performance";

export type RefreshCadenceType = "weekly" | "biweekly" | "monthly" | "release_driven" | "on_demand";

export type DatasetVersionStatus = "active" | "expired" | "revoked" | "rolled_back";

export type RefreshTrigger = "scheduled" | "on_demand";

export type EnvironmentRequestStatus = "active" | "paused" | "retired";

export interface RefreshPolicy {
  policy_id: string;
  policy_version: number;
  environment: Environment;
  dataset_name: string | null;
  cadence_type: RefreshCadenceType;
  interval_days: number | null;
  retention_days: number;
  grace_period_days: number;
  on_demand_allowed: boolean;
  is_active: boolean;
  created_at: string;
  updated_at: string;
}

export interface DatasetVersion {
  version_id: string;
  dataset_name: string;
  version_number: number;
  certification_report_id: string;
  masking_policy_name: string;
  masking_policy_version: number;
  masking_engine_version: string;
  storage_uri: string;
  size_bytes: number;
  row_counts: Record<string, number>;
  status: DatasetVersionStatus;
  created_at: string;
  created_by: string;
  retention_days: number;
  expires_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  revoked_by: string | null;
  rolled_back_at: string | null;
  notes: string;
  referenced_by_environments: Environment[];
}

export interface EnvironmentDatasetRequest {
  request_id: string;
  environment: Environment;
  dataset_name: string;
  current_version_id: string;
  current_version_number: number;
  status: EnvironmentRequestStatus;
  policy_id: string;
  policy_version: number;
  consumer: string;
  requested_by: string;
  requested_at: string;
  last_refresh_at: string | null;
  next_refresh_at: string | null;
}

export interface RefreshRunRecord {
  run_id: string;
  request_id: string;
  environment: Environment;
  dataset_name: string;
  trigger: RefreshTrigger;
  triggered_by: string;
  started_at: string;
  finished_at: string | null;
  previous_version_id: string | null;
  resulting_version_id: string | null;
  succeeded: boolean | null;
  detail: string;
}

export interface RollbackRecord {
  rollback_id: string;
  request_id: string;
  environment: Environment;
  dataset_name: string;
  from_version_id: string;
  from_version_number: number;
  to_version_id: string;
  to_version_number: number;
  performed_by: string;
  performed_at: string;
  reason: string;
}

export interface SchedulerRunResult {
  as_of: string;
  attempted_count: number;
  succeeded_count: number;
  failed_count: number;
  results: RefreshRunRecord[];
  errors: Array<Record<string, unknown>>;
}

// ---------------------------------------------------------------------
// capacity.py
// ---------------------------------------------------------------------

export interface DatasetVersionFootprint {
  version_id: string;
  dataset_name: string;
  version_number: number;
  status: DatasetVersionStatus;
  storage_footprint_bytes: number;
  row_counts: Record<string, number>;
  total_row_count: number;
  retention_days: number;
  referenced_by_environments: Environment[];
  physical_copy_count: number;
  estimated_compute_unit_hours: number;
}

export interface EnvironmentCapacityDemand {
  request_id: string;
  environment: Environment;
  dataset_name: string;
  current_version_id: string;
  current_version_number: number;
  attributed_storage_bytes: number;
  total_row_count: number;
  refresh_cadence_type: RefreshCadenceType;
  refresh_interval_days: number | null;
  retention_days: number;
  estimated_refreshes_per_year: number | null;
  estimated_annual_processing_volume_rows: number | null;
  estimated_annual_compute_unit_hours: number | null;
}

export interface CapacityPlan {
  generated_at: string;
  dataset_name: string | null;
  dataset_version_footprints: DatasetVersionFootprint[];
  environment_demands: EnvironmentCapacityDemand[];
  environment_count: number;
  distinct_dataset_version_count: number;
  naive_total_storage_bytes: number;
  shared_total_storage_bytes: number;
  storage_savings_bytes: number;
  storage_savings_pct: number;
}

export interface VacuumCandidate {
  version_id: string;
  dataset_name: string;
  version_number: number;
  status: DatasetVersionStatus;
  storage_uri: string;
  reclaimable_bytes: number;
  reason: string;
}

export interface EnvironmentCapacityRequirement {
  environment: Environment;
  target_pct_of_production: number;
  share_tier: string;
  rationale: string;
}

export interface IllustrativeCapacityScenario {
  scenario_id: string;
  label: string;
  production_baseline_bytes: number;
  requirements: EnvironmentCapacityRequirement[];
}

export interface IllustrativeCapacityPlan {
  scenario: IllustrativeCapacityScenario;
  generated_at: string;
  per_environment_naive_bytes: Record<string, number>;
  per_tier_shared_bytes: Record<string, number>;
  naive_total_bytes: number;
  shared_total_bytes: number;
  savings_bytes: number;
  savings_pct: number;
}

// ---------------------------------------------------------------------
// masking run summary (Phase 9 control-plane-local mirror -- see
// control_plane/artifacts/masking.py; not a libs/contracts type)
// ---------------------------------------------------------------------

export interface MaskingRunSummary {
  rows_processed: number;
  columns_masked: number;
  technique_counts: Record<string, number>;
  files_written: string[];
  warning_count: number;
  masking_engine_version: string;
  policy_name: string | null;
  policy_version: number | null;
  validation_passed: boolean;
  validation_checks: string[];
  validation_failures: string[];
}

export interface MaskingRunRecord {
  source_path: string;
  summary: MaskingRunSummary;
}

// ---------------------------------------------------------------------
// subsetting.py
// ---------------------------------------------------------------------

export type SubsettingStrategy =
  | "percentage"
  | "fixed_population"
  | "stratified"
  | "date_window"
  | "business_rule"
  | "risk_edge_case";

export type IntegrityStatus = "passed" | "passed_with_known_orphans" | "failed";

export interface SubsetSelectionCriteria {
  strategy: SubsettingStrategy;
  parameters: Record<string, string>;
  description: string;
  negative_testing: boolean;
}

export interface RelationshipEdge {
  parent_entity: string;
  child_entity: string;
  edge_count: number;
}

export interface SubsetManifest {
  manifest_id: string;
  version: number;
  created_at: string;
  scale_profile: string;
  anchor_entity: string;
  selection: SubsetSelectionCriteria;
  source_counts: Record<string, number>;
  selected_counts: Record<string, number>;
  relationship_edges: RelationshipEdge[];
  filter_criteria: Record<string, string>;
  estimated_source_storage_bytes: number;
  estimated_subset_storage_bytes: number;
  integrity_status: IntegrityStatus;
  known_orphan_counts: Record<string, number>;
  injected_negative_test_orphan_counts: Record<string, number>;
  integrity_findings: string[];
}

export interface SubsetManifestRecord {
  source_path: string;
  manifest: SubsetManifest;
}

// ---------------------------------------------------------------------
// synthetic.py
// ---------------------------------------------------------------------

export type DataProvenance = "masked_production_like" | "synthetic" | "negative_test";

export type ScenarioType =
  | "normal_claims"
  | "high_cost_claims"
  | "duplicate_claims"
  | "invalid_claim_references"
  | "expired_coverage"
  | "missing_provider"
  | "unusual_prescription_combinations"
  | "missing_laboratory_values"
  | "boundary_dates"
  | "null_heavy_records"
  | "very_large_claim_histories";

export interface ScenarioGenerationRecord {
  scenario: ScenarioType;
  provenance: DataProvenance;
  description: string;
  row_counts: Record<string, number>;
  anchor_ids: string[];
}

export interface SyntheticGenerationManifest {
  manifest_id: string;
  version: number;
  created_at: string;
  mode: string;
  base_estate_dir: string | null;
  base_subset_manifest_id: string | null;
  seed: number;
  id_prefix_convention: string;
  scenarios: ScenarioGenerationRecord[];
  total_row_counts: Record<string, number>;
  provenance_row_counts: Record<string, number>;
  estimated_output_storage_bytes: number;
}

export interface SyntheticManifestRecord {
  source_path: string;
  manifest: SyntheticGenerationManifest;
}

// ---------------------------------------------------------------------
// certification.py
// ---------------------------------------------------------------------

export type CertificationStatus = "draft" | "processing" | "failed" | "certified" | "published" | "revoked";

export type CertificationGateType =
  | "phi_pii_policy_coverage"
  | "masking_completion"
  | "referential_integrity"
  | "schema_validation"
  | "data_quality_thresholds"
  | "row_count_reconciliation"
  | "orphan_detection"
  | "provenance"
  | "manifest_generation"
  | "policy_version_recorded"
  | "masking_version_recorded";

export interface CertificationGateResult {
  gate: CertificationGateType;
  passed: boolean;
  detail: string;
  metrics: Record<string, string>;
}

export interface CertificationStatusEvent {
  status: CertificationStatus;
  occurred_at: string;
  actor: string;
  reason: string;
}

export interface CertificationReport {
  report_id: string;
  version: number;
  created_at: string;
  updated_at: string;
  status: CertificationStatus;
  status_history: CertificationStatusEvent[];
  dataset_name: string;
  scale_profile: string;
  subset_manifest_id: string | null;
  synthetic_generation_manifest_id: string | null;
  masking_policy_name: string;
  masking_policy_version: number;
  masking_engine_version: string;
  gates: CertificationGateResult[];
  row_count_reconciliation: Record<string, string>;
  integrity_signature: string | null;
  certified_at: string | null;
  published_at: string | null;
  revoked_at: string | null;
  revoked_reason: string | null;
  notes: string;
}

export interface CertificationReportRecord {
  source_path: string;
  report: CertificationReport;
}

// ---------------------------------------------------------------------
// health.py
// ---------------------------------------------------------------------

export interface HealthResponse {
  status: string;
  service: string;
}
