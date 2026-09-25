/** Single source of truth for the left-nav structure and route paths --
 * `routes/index.tsx` maps each `path` to its page component; `AppShell`
 * renders this same list as navigation, so the two never drift apart. */
export interface NavItem {
  path: string;
  label: string;
}

export interface NavSection {
  title: string;
  items: NavItem[];
}

export const NAV_SECTIONS: NavSection[] = [
  {
    title: "Overview",
    items: [{ path: "/", label: "Dashboard" }],
  },
  {
    title: "Data",
    items: [
      { path: "/data-sources", label: "Data Sources" },
      { path: "/catalog", label: "Data Catalog" },
      { path: "/discovery", label: "Sensitive Data Discovery" },
    ],
  },
  {
    title: "Pipeline",
    items: [
      { path: "/masking", label: "Masking Policies" },
      { path: "/subsetting", label: "Subsetting Jobs" },
      { path: "/synthetic", label: "Synthetic Data" },
      { path: "/certification", label: "Certification" },
    ],
  },
  {
    title: "Datasets & Environments",
    items: [
      { path: "/datasets", label: "Datasets" },
      { path: "/environments", label: "Environment Provisioning" },
      { path: "/refresh-calendar", label: "Refresh Calendar" },
      { path: "/capacity", label: "Capacity & Cost" },
    ],
  },
  {
    title: "Governance",
    items: [
      { path: "/audit-trail", label: "Audit Trail" },
      { path: "/platform-health", label: "Platform Health" },
    ],
  },
];
