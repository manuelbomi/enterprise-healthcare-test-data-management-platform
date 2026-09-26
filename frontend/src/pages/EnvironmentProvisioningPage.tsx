import { Link } from "react-router-dom";
import { lifecycleApi } from "@/api";
import type { EnvironmentDatasetRequest } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatDate, titleCase } from "@/lib/format";

/** Every environment's standing dataset request (Phase 7's real
 * `EnvironmentDatasetRequest` registry --
 * `GET /api/v1/lifecycle/environment-requests`). Read-only view; the
 * request/refresh/rollback write actions this data backs are exercised
 * by `scripts/demo_phase7_lifecycle.py` and covered by
 * `services/control-plane/tests/test_lifecycle_api.py` -- adding an
 * in-console write workflow is future scope (see `docs/problems/problems_phase_09.md`). */
export function EnvironmentProvisioningPage() {
  const requests = useApiData(() => lifecycleApi.listEnvironmentRequests());

  return (
    <>
      <PageHeader
        title="Environment Provisioning"
        description="Which dataset version each lower environment (DEV/QA/SIT/UAT/PERFORMANCE) currently points at -- Phase 7's real, shared-snapshot lifecycle registry."
      />
      <AsyncSection state={requests} loadingLabel="Loading environment requests">
        {(rows) => (
          <DataTable<EnvironmentDatasetRequest>
            caption={`${rows.length} environment request(s)`}
            getRowKey={(row) => row.request_id}
            rows={[...rows].sort((a, b) => a.environment.localeCompare(b.environment))}
            emptyMessage="No environment requests registered yet."
            columns={columns}
          />
        )}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<EnvironmentDatasetRequest>[] = [
  { key: "environment", header: "Environment", render: (row) => titleCase(row.environment) },
  { key: "dataset", header: "Dataset", render: (row) => row.dataset_name },
  { key: "version", header: "Current version", align: "right", render: (row) => `v${row.current_version_number}` },
  { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  { key: "consumer", header: "Consumer", render: (row) => row.consumer || "—" },
  { key: "last_refresh", header: "Last refresh", render: (row) => formatDate(row.last_refresh_at) },
  { key: "next_refresh", header: "Next refresh", render: (row) => formatDate(row.next_refresh_at) },
  {
    key: "detail",
    header: "",
    render: (row) => <Link to={`/datasets/${row.current_version_id}`}>View dataset →</Link>,
  },
];
