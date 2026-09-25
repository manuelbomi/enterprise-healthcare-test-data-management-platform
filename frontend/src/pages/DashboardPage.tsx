import { Link } from "react-router-dom";
import { capacityApi, catalogApi, certificationApi, lifecycleApi, maskingApi } from "@/api";
import { AsyncSection } from "@/components/AsyncSection";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { useApiData } from "@/hooks/useApiData";
import { formatBytes, formatNumber, formatPercent, formatRelativeToNow, titleCase } from "@/lib/format";

/**
 * Landing page: eight real, live-fetched tiles/sections, per the Phase 9
 * spec (datasets by status, PHI/PII classifications, masking coverage,
 * certification failures, upcoming refreshes, storage footprint,
 * compute utilization estimates, environment demand). Every section
 * fetches independently so one artifact type not existing yet (a fresh
 * checkout with no masking/certification runs generated) degrades that
 * one tile to an honest error state instead of blocking the rest of the
 * dashboard -- see `AsyncSection`.
 */
export function DashboardPage() {
  const datasetVersions = useApiData(() => lifecycleApi.listDatasetVersions());
  const catalogSummary = useApiData(() => catalogApi.getCatalogSummary());
  const maskingRuns = useApiData(() => maskingApi.listMaskingRuns());
  const certificationReports = useApiData(() => certificationApi.listCertificationReports());
  const environmentRequests = useApiData(() => lifecycleApi.listEnvironmentRequests());
  const capacityPlan = useApiData(() => capacityApi.getCapacityPlan());

  return (
    <>
      <PageHeader
        title="Dashboard"
        description="Live status across the certified test-data pipeline: catalog, masking, certification, datasets, and environment capacity."
      />

      <section aria-labelledby="datasets-by-status-heading" className="dashboard-section">
        <h2 id="datasets-by-status-heading">Datasets by status</h2>
        <AsyncSection state={datasetVersions} loadingLabel="Loading dataset versions">
          {(versions) => {
            const counts = countBy(versions, (v) => v.status);
            return (
              <div className="stat-grid">
                {Object.entries(counts).map(([status, count]) => (
                  <StatCard key={status} label={titleCase(status)} value={formatNumber(count)} />
                ))}
                {versions.length === 0 && <p>No dataset versions registered yet.</p>}
              </div>
            );
          }}
        </AsyncSection>
      </section>

      <section aria-labelledby="phi-pii-heading" className="dashboard-section">
        <h2 id="phi-pii-heading">PHI/PII classifications</h2>
        <AsyncSection state={catalogSummary} loadingLabel="Loading catalog summary">
          {(summary) => (
            <div className="stat-grid">
              <StatCard label="Total classified columns" value={formatNumber(summary.total_columns)} />
              <StatCard label="Datasets cataloged" value={formatNumber(summary.total_datasets)} />
              <StatCard
                label="Needing steward review"
                value={formatNumber(summary.needs_review)}
                tone={summary.needs_review > 0 ? "warning" : "good"}
              />
              {Object.entries(summary.by_category).map(([category, count]) => (
                <StatCard key={category} label={titleCase(category)} value={formatNumber(count)} />
              ))}
            </div>
          )}
        </AsyncSection>
      </section>

      <section aria-labelledby="masking-coverage-heading" className="dashboard-section">
        <h2 id="masking-coverage-heading">Masking coverage</h2>
        <AsyncSection state={maskingRuns} loadingLabel="Loading masking runs">
          {(runs) => {
            if (runs.length === 0) return <p>No masking runs discovered under the configured artifact root.</p>;
            const totalColumnsMasked = runs.reduce((t, r) => t + r.summary.columns_masked, 0);
            const totalRowsProcessed = runs.reduce((t, r) => t + r.summary.rows_processed, 0);
            const passedRuns = runs.filter((r) => r.summary.validation_passed).length;
            return (
              <div className="stat-grid">
                <StatCard label="Masking runs found" value={formatNumber(runs.length)} />
                <StatCard label="Column-values masked (all runs)" value={formatNumber(totalColumnsMasked)} />
                <StatCard label="Rows processed (all runs)" value={formatNumber(totalRowsProcessed)} />
                <StatCard
                  label="Runs passing validation"
                  value={`${passedRuns} / ${runs.length}`}
                  tone={passedRuns === runs.length ? "good" : "warning"}
                />
              </div>
            );
          }}
        </AsyncSection>
      </section>

      <section aria-labelledby="certification-failures-heading" className="dashboard-section">
        <h2 id="certification-failures-heading">Certification</h2>
        <AsyncSection state={certificationReports} loadingLabel="Loading certification reports">
          {(records) => {
            const failed = records.filter((r) => r.report.status === "failed");
            const published = records.filter((r) => r.report.status === "published");
            return (
              <div className="stat-grid">
                <StatCard label="Certification reports found" value={formatNumber(records.length)} />
                <StatCard
                  label="Failures"
                  value={formatNumber(failed.length)}
                  tone={failed.length > 0 ? "critical" : "good"}
                />
                <StatCard label="Published" value={formatNumber(published.length)} tone="good" />
                {failed.length > 0 && (
                  <div className="dashboard-section__list">
                    <p>Failed runs:</p>
                    <ul>
                      {failed.map((r) => (
                        <li key={r.report.report_id}>
                          {r.report.dataset_name} — {r.report.gates.filter((g) => !g.passed).length} gate(s) failed
                        </li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            );
          }}
        </AsyncSection>
      </section>

      <section aria-labelledby="upcoming-refreshes-heading" className="dashboard-section">
        <h2 id="upcoming-refreshes-heading">Upcoming refreshes</h2>
        <AsyncSection state={environmentRequests} loadingLabel="Loading environment requests">
          {(requests) => {
            const upcoming = [...requests]
              .filter((r) => r.next_refresh_at)
              .sort((a, b) => new Date(a.next_refresh_at!).getTime() - new Date(b.next_refresh_at!).getTime())
              .slice(0, 5);
            if (upcoming.length === 0) return <p>No environment requests with a scheduled next refresh.</p>;
            return (
              <ul className="dashboard-section__list">
                {upcoming.map((request) => (
                  <li key={request.request_id}>
                    <Link to={`/environments`}>
                      {titleCase(request.environment)} — {request.dataset_name}
                    </Link>{" "}
                    — {formatRelativeToNow(request.next_refresh_at)} ({request.next_refresh_at})
                  </li>
                ))}
              </ul>
            );
          }}
        </AsyncSection>
      </section>

      <section aria-labelledby="storage-footprint-heading" className="dashboard-section">
        <h2 id="storage-footprint-heading">Storage footprint</h2>
        <AsyncSection state={capacityPlan} loadingLabel="Loading capacity plan">
          {(plan) => (
            <div className="stat-grid">
              <StatCard label="Shared storage (actual)" value={formatBytes(plan.shared_total_storage_bytes)} />
              <StatCard label="Naive storage (if every env copied)" value={formatBytes(plan.naive_total_storage_bytes)} />
              <StatCard
                label="Savings from shared snapshots"
                value={formatPercent(plan.storage_savings_pct)}
                detail={formatBytes(plan.storage_savings_bytes)}
                tone="good"
              />
              <StatCard label="Distinct dataset versions" value={formatNumber(plan.distinct_dataset_version_count)} />
            </div>
          )}
        </AsyncSection>
      </section>

      <section aria-labelledby="compute-heading" className="dashboard-section">
        <h2 id="compute-heading">Compute utilization estimates</h2>
        <AsyncSection state={capacityPlan} loadingLabel="Loading capacity plan">
          {(plan) => {
            const totalAnnualHours = plan.environment_demands.reduce(
              (t, d) => t + (d.estimated_annual_compute_unit_hours ?? 0),
              0,
            );
            return (
              <div className="stat-grid">
                <StatCard label="Estimated annual compute-unit-hours" value={formatNumber(Math.round(totalAnnualHours))} />
                <StatCard
                  label="Dataset version footprints computed"
                  value={formatNumber(plan.dataset_version_footprints.length)}
                />
              </div>
            );
          }}
        </AsyncSection>
      </section>

      <section aria-labelledby="environment-demand-heading" className="dashboard-section">
        <h2 id="environment-demand-heading">Environment demand</h2>
        <AsyncSection state={capacityPlan} loadingLabel="Loading capacity plan">
          {(plan) => {
            if (plan.environment_demands.length === 0) return <p>No environment demand registered yet.</p>;
            return (
              <ul className="dashboard-section__list">
                {groupDemandByEnvironment(plan.environment_demands).map(([environment, demands]) => (
                  <li key={environment}>
                    <strong>{titleCase(environment)}</strong>: {demands.length} dataset(s),{" "}
                    {formatBytes(demands.reduce((t, d) => t + d.attributed_storage_bytes, 0))}
                  </li>
                ))}
              </ul>
            );
          }}
        </AsyncSection>
      </section>
    </>
  );
}

function countBy<T>(items: T[], key: (item: T) => string): Record<string, number> {
  const counts: Record<string, number> = {};
  for (const item of items) {
    const k = key(item);
    counts[k] = (counts[k] ?? 0) + 1;
  }
  return counts;
}

function groupDemandByEnvironment(
  demands: { environment: string; attributed_storage_bytes: number }[],
): [string, typeof demands][] {
  const groups = new Map<string, typeof demands>();
  for (const demand of demands) {
    const list = groups.get(demand.environment) ?? [];
    list.push(demand);
    groups.set(demand.environment, list);
  }
  return Array.from(groups.entries());
}
