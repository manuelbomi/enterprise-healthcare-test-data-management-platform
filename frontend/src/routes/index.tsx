import { createBrowserRouter } from "react-router-dom";
import { AppShell } from "@/components/AppShell";
import { AuditTrailPage } from "@/pages/AuditTrailPage";
import { CapacityCostPage } from "@/pages/CapacityCostPage";
import { CertificationPage } from "@/pages/CertificationPage";
import { DashboardPage } from "@/pages/DashboardPage";
import { DataCatalogPage } from "@/pages/DataCatalogPage";
import { DataSourcesPage } from "@/pages/DataSourcesPage";
import { DatasetDetailPage } from "@/pages/DatasetDetailPage";
import { DatasetsPage } from "@/pages/DatasetsPage";
import { EnvironmentProvisioningPage } from "@/pages/EnvironmentProvisioningPage";
import { MaskingPoliciesPage } from "@/pages/MaskingPoliciesPage";
import { NotFoundPage } from "@/pages/NotFoundPage";
import { PlatformHealthPage } from "@/pages/PlatformHealthPage";
import { RefreshCalendarPage } from "@/pages/RefreshCalendarPage";
import { SensitiveDataDiscoveryPage } from "@/pages/SensitiveDataDiscoveryPage";
import { SubsettingJobsPage } from "@/pages/SubsettingJobsPage";
import { SyntheticDataPage } from "@/pages/SyntheticDataPage";

/**
 * Route table. Every path here also appears in `navigation.ts`'s
 * `NAV_SECTIONS` (that file is the source of truth for the left-nav
 * structure; this file maps each of those paths to its page component).
 */
export const router = createBrowserRouter([
  {
    path: "/",
    element: <AppShell />,
    children: [
      { index: true, element: <DashboardPage /> },
      { path: "data-sources", element: <DataSourcesPage /> },
      { path: "catalog", element: <DataCatalogPage /> },
      { path: "discovery", element: <SensitiveDataDiscoveryPage /> },
      { path: "masking", element: <MaskingPoliciesPage /> },
      { path: "subsetting", element: <SubsettingJobsPage /> },
      { path: "synthetic", element: <SyntheticDataPage /> },
      { path: "certification", element: <CertificationPage /> },
      { path: "datasets", element: <DatasetsPage /> },
      { path: "datasets/:versionId", element: <DatasetDetailPage /> },
      { path: "environments", element: <EnvironmentProvisioningPage /> },
      { path: "refresh-calendar", element: <RefreshCalendarPage /> },
      { path: "capacity", element: <CapacityCostPage /> },
      { path: "audit-trail", element: <AuditTrailPage /> },
      { path: "platform-health", element: <PlatformHealthPage /> },
      { path: "*", element: <NotFoundPage /> },
    ],
  },
]);
