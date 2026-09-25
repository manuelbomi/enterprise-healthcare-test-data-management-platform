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
export * from "./types";
