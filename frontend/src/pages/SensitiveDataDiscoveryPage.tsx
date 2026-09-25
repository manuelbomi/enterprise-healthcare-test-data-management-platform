import { useState } from "react";
import { catalogApi } from "@/api";
import type { CatalogEntry } from "@/api/types";
import { needsReview } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatPercent } from "@/lib/format";

/**
 * A steward/auditor-focused view of the same real Phase 2 discovery
 * output `DataCatalogPage` shows in full: what the automated
 * classifiers found, how confident they were, and specifically what
 * still needs a human steward's sign-off (`needs_review`, computed
 * client-side per `libs/contracts.classification.ColumnClassification.
 * needs_review`'s rule -- see `api/types.ts`). No new endpoint: a
 * different lens on `GET /api/v1/catalog`.
 */
export function SensitiveDataDiscoveryPage() {
  const [showOnlyNeedsReview, setShowOnlyNeedsReview] = useState(true);
  const entries = useApiData(
    () => catalogApi.listCatalogEntries(showOnlyNeedsReview ? { needs_review: true } : {}),
    [showOnlyNeedsReview],
  );

  return (
    <>
      <PageHeader
        title="Sensitive Data Discovery"
        description="What the Phase 2 rule-based/schema-based PHI/PII classifiers found, and which classifications still need a data steward's review."
      />

      <fieldset className="filter-bar">
        <legend className="visually-hidden">Discovery filters</legend>
        <label>
          <input
            type="checkbox"
            checked={showOnlyNeedsReview}
            onChange={(e) => setShowOnlyNeedsReview(e.target.checked)}
          />
          Show only columns needing steward review
        </label>
      </fieldset>

      <AsyncSection state={entries} loadingLabel="Loading discovery results">
        {(rows) => {
          const byDetector = groupByDetector(rows);
          return (
            <>
              <div className="stat-grid">
                <StatCard label={showOnlyNeedsReview ? "Needing review" : "Matching columns"} value={rows.length} />
                <StatCard label="Detectors that fired" value={byDetector.size} />
                <StatCard
                  label="Average confidence"
                  value={formatPercent(average(rows.map((r) => r.classification.confidence)), 0)}
                />
              </div>

              <DataTable<CatalogEntry>
                caption="Discovered PHI/PII columns"
                getRowKey={(row) => `${row.classification.source_system}/${row.classification.dataset}/${row.classification.column}`}
                columns={columns}
                rows={rows}
                emptyMessage={
                  showOnlyNeedsReview
                    ? "Nothing currently needs steward review."
                    : "No catalog entries found."
                }
              />
            </>
          );
        }}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<CatalogEntry>[] = [
  { key: "source", header: "Source system", render: (row) => row.classification.source_system },
  { key: "dataset", header: "Dataset", render: (row) => row.classification.dataset },
  { key: "column", header: "Column", render: (row) => <code>{row.classification.column}</code> },
  { key: "category", header: "Category", render: (row) => (row.classification.category ? <StatusBadge status={row.classification.category} /> : "—") },
  { key: "detector", header: "Detector", render: (row) => row.classification.detector },
  { key: "confidence", header: "Confidence", align: "right", render: (row) => formatPercent(row.classification.confidence, 0) },
  { key: "reason", header: "Reason", render: (row) => row.classification.reason || "—" },
  {
    key: "review",
    header: "Needs review?",
    render: (row) => (
      <span className={`badge badge--${needsReview(row.classification) ? "warning" : "good"}`}>
        {needsReview(row.classification) ? "Yes" : "No"}
      </span>
    ),
  },
];

function groupByDetector(rows: CatalogEntry[]): Map<string, CatalogEntry[]> {
  const map = new Map<string, CatalogEntry[]>();
  for (const row of rows) {
    const list = map.get(row.classification.detector) ?? [];
    list.push(row);
    map.set(row.classification.detector, list);
  }
  return map;
}

function average(values: number[]): number {
  if (values.length === 0) return 0;
  return values.reduce((t, v) => t + v, 0) / values.length;
}
