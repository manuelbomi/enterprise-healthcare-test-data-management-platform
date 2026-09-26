/** Barrel export: pages import `@/api` rather than reaching into
 * individual domain modules, so call sites read `api.listCatalogEntries(...)`
 * consistently. See `src/api/README.md`. */
export * from "./client";
export * as catalogApi from "./catalog";
export * as lifecycleApi from "./lifecycle";
export * as capacityApi from "./capacity";
export * as maskingApi from "./masking";
export * as subsettingApi from "./subsetting";
export * as syntheticApi from "./synthetic";
export * as certificationApi from "./certification";
export * as healthApi from "./health";
// Phase 18A (docs/problems/problems_final_review.md P1-4): these three did not
// exist before this phase -- no frontend code called any Phase 11/13
// audit/evidence endpoint, or any Phase 10 governance endpoint, at all.
export * as auditApi from "./audit";
export * as evidenceApi from "./evidence";
export * as governanceApi from "./governance";
export * from "./types";
