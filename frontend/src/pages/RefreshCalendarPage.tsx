import { lifecycleApi } from "@/api";
import type { EnvironmentDatasetRequest, RefreshPolicy } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useApiData } from "@/hooks/useApiData";
import { formatDate, formatRelativeToNow, titleCase } from "@/lib/format";

/** Refresh Calendar: real refresh policies (cadence per environment,
 * Phase 7) plus every environment request's actual computed
 * `next_refresh_at`, sorted chronologically -- and what the scheduler
 * abstraction (`RefreshOrchestrator`) currently considers due right
 * now (`GET /api/v1/lifecycle/scheduler/due`). */
export function RefreshCalendarPage() {
  const policies = useApiData(() => lifecycleApi.listRefreshPolicies());
  const requests = useApiData(() => lifecycleApi.listEnvironmentRequests());
  const due = useApiData(() => lifecycleApi.listDueRefreshes());

  return (
    <>
      <PageHeader
        title="Refresh Calendar"
        description="Configured refresh cadence per environment and the real, computed schedule for every environment request."
      />

      <section aria-labelledby="due-now-heading" className="dashboard-section">
        <h2 id="due-now-heading">Due for refresh right now</h2>
        <AsyncSection state={due} loadingLabel="Loading due refreshes">
          {(rows) =>
            rows.length === 0 ? (
              <p>Nothing is currently due for refresh.</p>
            ) : (
              <DataTable<EnvironmentDatasetRequest>
                caption="Environment requests due for refresh"
                getRowKey={(row) => row.request_id}
                rows={rows}
                columns={dueColumns}
              />
            )
          }
        </AsyncSection>
      </section>

      <section aria-labelledby="policies-heading" className="dashboard-section">
        <h2 id="policies-heading">Refresh policies</h2>
        <AsyncSection state={policies} loadingLabel="Loading refresh policies">
          {(rows) => (
            <DataTable<RefreshPolicy>
              caption={`${rows.length} configured refresh polic${rows.length === 1 ? "y" : "ies"}`}
              getRowKey={(row) => row.policy_id}
              rows={rows}
              emptyMessage="No refresh policies configured yet (defaults are seeded lazily on first environment request)."
              columns={policyColumns}
            />
          )}
        </AsyncSection>
      </section>

      <section aria-labelledby="schedule-heading" className="dashboard-section">
        <h2 id="schedule-heading">Upcoming schedule</h2>
        <AsyncSection state={requests} loadingLabel="Loading environment requests">
          {(rows) => {
            const upcoming = [...rows]
              .filter((r) => r.next_refresh_at)
              .sort((a, b) => new Date(a.next_refresh_at!).getTime() - new Date(b.next_refresh_at!).getTime());
            return (
              <DataTable<EnvironmentDatasetRequest>
                caption="All environment requests with a scheduled next refresh"
                getRowKey={(row) => row.request_id}
                rows={upcoming}
                emptyMessage="No environment requests with a scheduled next refresh (release-driven/on-demand cadences have none by design)."
                columns={scheduleColumns}
              />
            );
          }}
        </AsyncSection>
      </section>
    </>
  );
}

const dueColumns: DataTableColumn<EnvironmentDatasetRequest>[] = [
  { key: "environment", header: "Environment", render: (row) => titleCase(row.environment) },
  { key: "dataset", header: "Dataset", render: (row) => row.dataset_name },
  { key: "next_refresh", header: "Next refresh at", render: (row) => formatDate(row.next_refresh_at) },
];

const policyColumns: DataTableColumn<RefreshPolicy>[] = [
  { key: "environment", header: "Environment", render: (row) => titleCase(row.environment) },
  { key: "dataset", header: "Dataset", render: (row) => row.dataset_name ?? "(environment-wide default)" },
  { key: "cadence", header: "Cadence", render: (row) => titleCase(row.cadence_type) },
  { key: "interval", header: "Interval (days)", align: "right", render: (row) => (row.interval_days ?? "—").toString() },
  { key: "retention", header: "Retention (days)", align: "right", render: (row) => row.retention_days.toString() },
  { key: "on_demand", header: "On-demand allowed", render: (row) => (row.on_demand_allowed ? "Yes" : "No") },
];

const scheduleColumns: DataTableColumn<EnvironmentDatasetRequest>[] = [
  { key: "environment", header: "Environment", render: (row) => titleCase(row.environment) },
  { key: "dataset", header: "Dataset", render: (row) => row.dataset_name },
  { key: "next_refresh", header: "Next refresh", render: (row) => formatDate(row.next_refresh_at) },
  { key: "relative", header: "Relative", render: (row) => formatRelativeToNow(row.next_refresh_at) },
];
