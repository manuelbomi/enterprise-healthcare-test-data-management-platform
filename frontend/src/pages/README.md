# pages

Top-level, route-mounted screens (Phase 9). A page component composes
smaller components from `../components`; it should not itself contain
business logic beyond fetching data via `../api`/`../hooks` and handling
page-level state (filters, etc.).

## Inventory

| Page | Route | Backing data |
|---|---|---|
| `DashboardPage` | `/` | Live, composed from catalog/lifecycle/masking/certification/capacity APIs |
| `DataSourcesPage` | `/data-sources` | Real catalog data, grouped by source system |
| `DataCatalogPage` | `/catalog` | Real, filterable Phase 2 catalog |
| `SensitiveDataDiscoveryPage` | `/discovery` | Real Phase 2 catalog, steward-review lens |
| `MaskingPoliciesPage` | `/masking` | Real Phase 9 `GET /api/v1/masking/runs` |
| `SubsettingJobsPage` | `/subsetting` | Real Phase 9 `GET /api/v1/subsetting/manifests` |
| `SyntheticDataPage` | `/synthetic` | Real Phase 9 `GET /api/v1/synthetic/manifests` |
| `CertificationPage` | `/certification` | Real Phase 9 `GET /api/v1/certification/reports` |
| `DatasetsPage` | `/datasets` | Real Phase 7 `GET /api/v1/lifecycle/dataset-versions` |
| `DatasetDetailPage` | `/datasets/:versionId` | Composed from 4 real endpoints -- see its module docstring |
| `EnvironmentProvisioningPage` | `/environments` | Real Phase 7 environment requests |
| `RefreshCalendarPage` | `/refresh-calendar` | Real Phase 7 refresh policies/schedule |
| `CapacityCostPage` | `/capacity` | Real Phase 8 capacity plan + labeled illustrative scenario |
| `AuditTrailPage` | `/audit-trail` | Real `GET /api/v1/audit/events`, filterable table (Phase 18A) |
| `PlatformHealthPage` | `/platform-health` | Real (minimal) Phase 0 health endpoint |

See `problems_phase_09.md` for the per-page reasoning behind which pages
got new Phase 9 endpoints vs. remained honest placeholders.
