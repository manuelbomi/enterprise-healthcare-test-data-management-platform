import { Link } from "react-router-dom";
import { catalogApi } from "@/api";
import type { CatalogDatasetRow } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatNumber } from "@/lib/format";

/**
 * A source-system-centric view over the same real Phase 2 catalog data
 * `DataCatalogPage` shows column-by-column -- grouped by
 * `source_system` (`GET /api/v1/catalog/datasets`), matching the five
 * heterogeneous simulated source systems Phase 1 built (PostgreSQL,
 * Parquet object storage, S3-style NDJSON, ADLS-style CSV, and a partner
 * feed). No new endpoint needed: this is a different aggregation of the
 * same real data the catalog API already serves.
 */
export function DataSourcesPage() {
  const datasets = useApiData(() => catalogApi.listCatalogDatasets());

  return (
    <>
      <PageHeader
        title="Data Sources"
        description="Source systems known to the PHI/PII data catalog, grouped from the real Phase 2 discovery output."
      />
      <AsyncSection state={datasets} loadingLabel="Loading data sources">
        {(rows) => {
          const bySource = groupBySource(rows);
          return (
            <>
              <div className="stat-grid">
                <div className="stat-card">
                  <dl>
                    <dt className="stat-card__label">Source systems</dt>
                    <dd className="stat-card__value">{formatNumber(bySource.size)}</dd>
                  </dl>
                </div>
              </div>
              {Array.from(bySource.entries()).map(([source, sourceRows]) => (
                <section key={source} className="dashboard-section" aria-labelledby={`source-${source}`}>
                  <h2 id={`source-${source}`}>{source}</h2>
                  <DataTable<CatalogDatasetRow>
                    caption={`Datasets in ${source}`}
                    getRowKey={(row) => `${row.source_system}/${row.dataset}`}
                    columns={columns}
                    rows={sourceRows}
                  />
                </section>
              ))}
            </>
          );
        }}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<CatalogDatasetRow>[] = [
  {
    key: "dataset",
    header: "Dataset",
    render: (row) => (
      <Link to={`/catalog?dataset=${encodeURIComponent(row.dataset)}&source_system=${encodeURIComponent(row.source_system)}`}>
        {row.dataset}
      </Link>
    ),
  },
  { key: "column_count", header: "Columns", align: "right", render: (row) => formatNumber(row.column_count) },
  {
    key: "most_severe_category",
    header: "Most severe classification",
    render: (row) => (row.most_severe_category ? <StatusBadge status={row.most_severe_category} /> : "—"),
  },
  { key: "owner", header: "Owner", render: (row) => row.owner },
];

function groupBySource(rows: CatalogDatasetRow[]): Map<string, CatalogDatasetRow[]> {
  const map = new Map<string, CatalogDatasetRow[]>();
  for (const row of rows) {
    const list = map.get(row.source_system) ?? [];
    list.push(row);
    map.set(row.source_system, list);
  }
  return map;
}
