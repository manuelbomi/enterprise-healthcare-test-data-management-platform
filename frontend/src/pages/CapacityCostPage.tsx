import { capacityApi } from "@/api";
import type { DatasetVersionFootprint, VacuumCandidate } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatBytes, formatNumber, formatPercent } from "@/lib/format";

/** Capacity & Cost: the real, DB-backed naive-vs-shared storage
 * comparison and vacuum candidates (Phase 8), plus the pure,
 * clearly-labeled illustrative percentage-of-production model
 * (`ROADMAP.md`'s "Production: 100 TB, QA 10%, ..." example) -- never
 * presented as a measurement, per `docs/CAPACITY_COST_TRADEOFFS.md`. */
export function CapacityCostPage() {
  const plan = useApiData(() => capacityApi.getCapacityPlan());
  const vacuumCandidates = useApiData(() => capacityApi.getVacuumCandidates());
  const illustrative = useApiData(() => capacityApi.getIllustrativeCapacityPlan(100));

  return (
    <>
      <PageHeader
        title="Capacity & Cost"
        description="Real, DB-backed storage/compute capacity aggregated from Phase 7's dataset-version registry, plus vacuum candidates and a clearly-labeled illustrative scenario model."
      />

      <section aria-labelledby="plan-heading" className="dashboard-section">
        <h2 id="plan-heading">Real capacity plan</h2>
        <AsyncSection state={plan} loadingLabel="Loading capacity plan">
          {(data) => (
            <>
              <div className="stat-grid">
                <StatCard label="Shared storage (actual)" value={formatBytes(data.shared_total_storage_bytes)} />
                <StatCard label="Naive storage (if every env copied)" value={formatBytes(data.naive_total_storage_bytes)} />
                <StatCard label="Savings" value={formatPercent(data.storage_savings_pct)} detail={formatBytes(data.storage_savings_bytes)} tone="good" />
                <StatCard label="Environments" value={formatNumber(data.environment_count)} />
                <StatCard label="Distinct dataset versions" value={formatNumber(data.distinct_dataset_version_count)} />
              </div>
              <DataTable<DatasetVersionFootprint>
                caption="Per-dataset-version footprint"
                getRowKey={(row) => row.version_id}
                rows={data.dataset_version_footprints}
                emptyMessage="No dataset version footprints computed yet."
                columns={footprintColumns}
              />
            </>
          )}
        </AsyncSection>
      </section>

      <section aria-labelledby="vacuum-heading" className="dashboard-section">
        <h2 id="vacuum-heading">Vacuum candidates</h2>
        <p>
          Dataset versions safe to physically delete: terminal status and referenced by zero environments.
          Read-only — see <code>docs/problems/problems_phase_08.md</code> P8-3.
        </p>
        <AsyncSection state={vacuumCandidates} loadingLabel="Loading vacuum candidates">
          {(rows) => (
            <DataTable<VacuumCandidate>
              caption={`${rows.length} vacuum candidate(s)`}
              getRowKey={(row) => row.version_id}
              rows={rows}
              emptyMessage="No versions are currently safe to vacuum."
              columns={vacuumColumns}
            />
          )}
        </AsyncSection>
      </section>

      <section aria-labelledby="illustrative-heading" className="dashboard-section">
        <h2 id="illustrative-heading">Illustrative scenario (modeled, not measured)</h2>
        <p className="callout callout--info">
          The figures below are a pure, configurable calculation against a hypothetical 100&nbsp;TB production
          baseline (<code>ROADMAP.md</code> Phase 8&rsquo;s worked example) — never a measurement of this
          environment&rsquo;s real data. See <code>docs/CAPACITY_COST_TRADEOFFS.md</code>.
        </p>
        <AsyncSection state={illustrative} loadingLabel="Loading illustrative plan">
          {(data) => (
            <div className="stat-grid">
              <StatCard label="Naive total (illustrative)" value={formatBytes(data.naive_total_bytes)} />
              <StatCard label="Shared-by-tier total (illustrative)" value={formatBytes(data.shared_total_bytes)} />
              <StatCard label="Illustrative savings" value={formatPercent(data.savings_pct)} detail={formatBytes(data.savings_bytes)} />
            </div>
          )}
        </AsyncSection>
      </section>
    </>
  );
}

const footprintColumns: DataTableColumn<DatasetVersionFootprint>[] = [
  { key: "dataset", header: "Dataset", render: (row) => `${row.dataset_name} v${row.version_number}` },
  { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  { key: "storage", header: "Storage", align: "right", render: (row) => formatBytes(row.storage_footprint_bytes) },
  { key: "rows", header: "Total rows", align: "right", render: (row) => formatNumber(row.total_row_count) },
  { key: "copies", header: "Physical copies", align: "right", render: (row) => row.physical_copy_count.toString() },
  { key: "compute", header: "Est. compute-unit-hours", align: "right", render: (row) => row.estimated_compute_unit_hours.toFixed(1) },
];

const vacuumColumns: DataTableColumn<VacuumCandidate>[] = [
  { key: "dataset", header: "Dataset", render: (row) => `${row.dataset_name} v${row.version_number}` },
  { key: "status", header: "Status", render: (row) => <StatusBadge status={row.status} /> },
  { key: "reclaimable", header: "Reclaimable", align: "right", render: (row) => formatBytes(row.reclaimable_bytes) },
  { key: "reason", header: "Reason", render: (row) => row.reason },
];
