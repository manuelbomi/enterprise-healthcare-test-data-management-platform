import { useSearchParams } from "react-router-dom";
import { catalogApi } from "@/api";
import type { CatalogEntry, ClassificationTier, SensitivityCategory } from "@/api/types";
import { needsReview } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatPercent, titleCase } from "@/lib/format";

const CATEGORIES: SensitivityCategory[] = ["direct_identifier", "quasi_identifier", "phi", "pii", "sensitive", "non_sensitive"];
const TIERS: ClassificationTier[] = [
  "direct_identifier",
  "quasi_identifier",
  "sensitive_clinical_attribute",
  "non_sensitive",
];

/**
 * The full, filterable PHI/PII data catalog (Phase 2's real
 * classification output, `GET /api/v1/catalog`). Filters are stored in
 * the URL (`useSearchParams`) so a link from `DataSourcesPage` or
 * `SensitiveDataDiscoveryPage` can deep-link into a pre-filtered view.
 */
export function DataCatalogPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const sourceSystem = searchParams.get("source_system") ?? "";
  const dataset = searchParams.get("dataset") ?? "";
  const category = (searchParams.get("category") as SensitivityCategory | null) ?? "";
  const tier = (searchParams.get("tier") as ClassificationTier | null) ?? "";

  const entries = useApiData(
    () =>
      catalogApi.listCatalogEntries({
        source_system: sourceSystem || undefined,
        dataset: dataset || undefined,
        category: (category as SensitivityCategory) || undefined,
        tier: (tier as ClassificationTier) || undefined,
      }),
    [sourceSystem, dataset, category, tier],
  );

  function updateFilter(key: string, value: string) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  }

  return (
    <>
      <PageHeader
        title="Data Catalog"
        description="Every classified column the Phase 2 discovery engine found, with its masking requirement, owner, and retention classification."
      />

      <form className="filter-bar" role="search" aria-label="Catalog filters">
        <label>
          Source system
          <input
            type="text"
            value={sourceSystem}
            onChange={(e) => updateFilter("source_system", e.target.value)}
            placeholder="e.g. postgres_enrollment"
          />
        </label>
        <label>
          Dataset
          <input type="text" value={dataset} onChange={(e) => updateFilter("dataset", e.target.value)} placeholder="e.g. member" />
        </label>
        <label>
          Category
          <select value={category} onChange={(e) => updateFilter("category", e.target.value)}>
            <option value="">All categories</option>
            {CATEGORIES.map((c) => (
              <option key={c} value={c}>
                {titleCase(c)}
              </option>
            ))}
          </select>
        </label>
        <label>
          Tier
          <select value={tier} onChange={(e) => updateFilter("tier", e.target.value)}>
            <option value="">All tiers</option>
            {TIERS.map((t) => (
              <option key={t} value={t}>
                {titleCase(t)}
              </option>
            ))}
          </select>
        </label>
      </form>

      <AsyncSection state={entries} loadingLabel="Loading catalog entries">
        {(rows) => (
          <DataTable<CatalogEntry>
            caption={`${rows.length} catalog ${rows.length === 1 ? "entry" : "entries"} matching the current filters`}
            getRowKey={(row) => `${row.classification.source_system}/${row.classification.dataset}/${row.classification.column}`}
            columns={columns}
            rows={rows}
            emptyMessage="No catalog entries match the current filters."
          />
        )}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<CatalogEntry>[] = [
  { key: "source", header: "Source system", render: (row) => row.classification.source_system },
  { key: "dataset", header: "Dataset", render: (row) => row.classification.dataset },
  { key: "column", header: "Column", render: (row) => <code>{row.classification.column}</code> },
  { key: "category", header: "Category", render: (row) => (row.classification.category ? <StatusBadge status={row.classification.category} /> : "—") },
  { key: "tier", header: "Tier", render: (row) => titleCase(row.classification.tier) },
  { key: "masking", header: "Masking requirement", render: (row) => titleCase(row.masking_requirement) },
  { key: "confidence", header: "Confidence", align: "right", render: (row) => formatPercent(row.classification.confidence, 0) },
  { key: "method", header: "Method", render: (row) => titleCase(row.classification.method) },
  { key: "owner", header: "Owner", render: (row) => row.owner },
  {
    key: "review",
    header: "Review status",
    render: (row) => <ReviewStatusBadge classification={row.classification} />,
  },
];

function ReviewStatusBadge({ classification }: { classification: CatalogEntry["classification"] }) {
  if (needsReview(classification)) {
    return <span className="badge badge--warning">Needs review</span>;
  }
  if (classification.confirmed_by) {
    return <span className="badge badge--good">Steward-confirmed</span>;
  }
  return <span className="badge badge--neutral">Automated (confident)</span>;
}
