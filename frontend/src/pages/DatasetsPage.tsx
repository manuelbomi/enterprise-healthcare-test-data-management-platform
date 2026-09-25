import { Link } from "react-router-dom";
import { lifecycleApi } from "@/api";
import type { DatasetVersion } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatBytes, formatDate, titleCase } from "@/lib/format";

/** Every registered `DatasetVersion` (Phase 7's real, DB-backed
 * dataset-version registry -- `GET /api/v1/lifecycle/dataset-versions`).
 * Links through to `DatasetDetailPage` for the full composed view. */
export function DatasetsPage() {
  const versions = useApiData(() => lifecycleApi.listDatasetVersions());

  return (
    <>
      <PageHeader
        title="Datasets"
        description="Every registered, immutable dataset version -- Phase 7's real dataset-version registry."
      />
      <AsyncSection state={versions} loadingLabel="Loading dataset versions">
        {(rows) => (
          <DataTable<DatasetVersion>
            caption={`${rows.length} dataset version(s) registered`}
            getRowKey={(row) => row.version_id}
            rows={[...rows].sort((a, b) => a.dataset_name.localeCompare(b.dataset_name) || b.version_number - a.version_number)}
            emptyMessage="No dataset versions registered yet."
            columns={columns}
          />
        )}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<DatasetVersion>[] = [
  {
    key: "dataset",
    header: "Dataset",
    render: (row) => <Link to={`/datasets/${row.version_id}`}>{row.dataset_name}</Link>,
  },
  { key: "version", header: "Version", align: "right", render: (row) => `v${row.version_number}` },
  { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  { key: "storage", header: "Storage", align: "right", render: (row) => formatBytes(row.size_bytes) },
  {
    key: "environments",
    header: "Referenced by",
    render: (row) => (row.referenced_by_environments.length > 0 ? row.referenced_by_environments.map(titleCase).join(", ") : "—"),
  },
  { key: "created", header: "Created", render: (row) => formatDate(row.created_at) },
];
