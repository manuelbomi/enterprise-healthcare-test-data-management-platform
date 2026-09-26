import { Link, useParams } from "react-router-dom";
import { capacityApi, certificationApi, lifecycleApi, subsettingApi } from "@/api";
import { AsyncSection } from "@/components/AsyncSection";
import { ErrorState } from "@/components/ErrorState";
import { LoadingState } from "@/components/LoadingState";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatBytes, formatDate, formatNumber, titleCase } from "@/lib/format";

/**
 * Dataset Detail page: composes every field the Phase 9 spec requires
 * (lineage, source systems, masking policy, subset policy, dataset
 * version, certification, row counts, referential-integrity status,
 * storage footprint, consumer environments) from FOUR real endpoints,
 * because no single endpoint carries all of it -- see
 * `docs/problems/problems_phase_09.md` for the composition documented in full:
 *
 * 1. `GET /api/v1/lifecycle/dataset-versions/{id}` -- the dataset
 *    version itself: status, masking policy name/version/engine
 *    version, storage_uri, row_counts, referenced_by_environments.
 * 2. `GET /api/v1/certification/reports/{certification_report_id}`
 *    (Phase 9) -- certification status/gates, including the
 *    REFERENTIAL_INTEGRITY gate this page surfaces as the
 *    referential-integrity status, and the `subset_manifest_id` used
 *    for step 3.
 * 3. `GET /api/v1/subsetting/manifests/{subset_manifest_id}` (Phase 9,
 *    only if the certification report recorded one) -- the subset
 *    policy (strategy/parameters/description) and its own
 *    `IntegrityStatus` as a second, corroborating referential-integrity
 *    signal.
 * 4. `GET /api/v1/capacity/dataset-versions/{id}/footprint` (Phase 8)
 *    -- the measured storage footprint and estimated compute demand.
 *
 * "Source systems" is intentionally not claimed as a precise per-version
 * lineage edge: no artifact records which of the five simulated source
 * systems contributed to a specific dataset version's rows (the subset
 * manifest records entity row counts, not source systems). This page
 * links to the Data Catalog instead of fabricating that link -- see
 * `docs/problems/problems_phase_09.md`.
 */
export function DatasetDetailPage() {
  const { versionId } = useParams<{ versionId: string }>();
  const version = useApiData(() => lifecycleApi.getDatasetVersion(versionId!), [versionId]);

  const certification = useApiData(
    () =>
      version.data
        ? certificationApi.getCertificationReport(version.data.certification_report_id)
        : Promise.resolve(null),
    [version.data?.certification_report_id],
  );

  const subsetManifestId = certification.data?.report.subset_manifest_id ?? null;
  const subsetManifest = useApiData(
    () => (subsetManifestId ? subsettingApi.getSubsetManifest(subsetManifestId) : Promise.resolve(null)),
    [subsetManifestId],
  );

  const footprint = useApiData(
    () => (versionId ? capacityApi.getDatasetVersionFootprint(versionId) : Promise.resolve(null)),
    [versionId],
  );

  const environmentRequests = useApiData(
    () => (version.data ? lifecycleApi.listEnvironmentRequests({ dataset_name: version.data.dataset_name }) : Promise.resolve([])),
    [version.data?.dataset_name],
  );

  if (!versionId) {
    return <ErrorState error={new Error("No dataset version id in the URL.")} />;
  }

  return (
    <AsyncSection state={version} loadingLabel="Loading dataset version">
      {(datasetVersion) => (
        <>
          <PageHeader
            title={`${datasetVersion.dataset_name} — v${datasetVersion.version_number}`}
            description={datasetVersion.notes || "Registered dataset version (Phase 7 lifecycle registry)."}
            actions={<StatusBadge status={datasetVersion.status} />}
          />

          <section aria-labelledby="dataset-version-heading" className="dashboard-section">
            <h2 id="dataset-version-heading">Dataset version</h2>
            <div className="stat-grid">
              <StatCard label="Version" value={`v${datasetVersion.version_number}`} />
              <StatCard label="Status" value={<StatusBadge status={datasetVersion.status} />} />
              <StatCard label="Created" value={formatDate(datasetVersion.created_at)} detail={datasetVersion.created_by} />
              <StatCard label="Retention" value={`${datasetVersion.retention_days} days`} detail={`Expires ${formatDate(datasetVersion.expires_at)}`} />
              <StatCard label="Storage URI" value={<code className="mono-wrap">{datasetVersion.storage_uri}</code>} />
            </div>
            {datasetVersion.status === "revoked" && (
              <p className="callout callout--critical">
                Revoked {formatDate(datasetVersion.revoked_at)} by {datasetVersion.revoked_by}: {datasetVersion.revoked_reason}
              </p>
            )}
          </section>

          <section aria-labelledby="row-counts-heading" className="dashboard-section">
            <h2 id="row-counts-heading">Row counts</h2>
            {Object.keys(datasetVersion.row_counts).length === 0 ? (
              <p>No row counts recorded for this version.</p>
            ) : (
              <ul className="dashboard-section__list">
                {Object.entries(datasetVersion.row_counts).map(([entity, count]) => (
                  <li key={entity}>
                    {entity}: {formatNumber(count)}
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-labelledby="masking-policy-heading" className="dashboard-section">
            <h2 id="masking-policy-heading">Masking policy</h2>
            <div className="stat-grid">
              <StatCard label="Policy" value={datasetVersion.masking_policy_name} detail={`v${datasetVersion.masking_policy_version}`} />
              <StatCard label="Masking engine version" value={datasetVersion.masking_engine_version} />
            </div>
          </section>

          <section aria-labelledby="subset-policy-heading" className="dashboard-section">
            <h2 id="subset-policy-heading">Subset policy</h2>
            {certification.loading || subsetManifest.loading ? (
              <LoadingState label="Loading subset policy" />
            ) : subsetManifest.data ? (
              <div className="stat-grid">
                <StatCard label="Strategy" value={titleCase(subsetManifest.data.manifest.selection.strategy)} />
                <StatCard label="Description" value={subsetManifest.data.manifest.selection.description || "—"} />
                <StatCard label="Integrity (subset stage)" value={<StatusBadge status={subsetManifest.data.manifest.integrity_status} />} />
              </div>
            ) : (
              <p>
                No subset manifest recorded on this version&rsquo;s certification report (dataset may have been
                certified from an existing estate directly).
              </p>
            )}
          </section>

          <section aria-labelledby="certification-heading" className="dashboard-section">
            <h2 id="certification-heading">Certification</h2>
            {certification.loading ? (
              <LoadingState label="Loading certification report" />
            ) : certification.error ? (
              <ErrorState error={certification.error} onRetry={certification.reload} />
            ) : certification.data ? (
              <>
                <div className="stat-grid">
                  <StatCard label="Status" value={<StatusBadge status={certification.data.report.status} />} />
                  <StatCard
                    label="Gates passed"
                    value={`${certification.data.report.gates.filter((g) => g.passed).length} / ${certification.data.report.gates.length}`}
                  />
                  <StatCard label="Certified at" value={formatDate(certification.data.report.certified_at)} />
                  <StatCard label="Published at" value={formatDate(certification.data.report.published_at)} />
                </div>
                <h3>Referential-integrity status</h3>
                {(() => {
                  const gate = certification.data.report.gates.find((g) => g.gate === "referential_integrity");
                  return gate ? (
                    <p>
                      <span className={`badge badge--${gate.passed ? "good" : "critical"}`}>
                        {gate.passed ? "PASS" : "FAIL"}
                      </span>{" "}
                      {gate.detail}
                    </p>
                  ) : (
                    <p>No referential-integrity gate recorded on this report.</p>
                  );
                })()}
              </>
            ) : (
              <p>No certification report found for id {datasetVersion.certification_report_id}.</p>
            )}
          </section>

          <section aria-labelledby="storage-footprint-heading" className="dashboard-section">
            <h2 id="storage-footprint-heading">Storage footprint</h2>
            <AsyncSection state={footprint} loadingLabel="Loading capacity footprint">
              {(fp) =>
                fp ? (
                  <div className="stat-grid">
                    <StatCard label="Storage footprint" value={formatBytes(fp.storage_footprint_bytes)} />
                    <StatCard label="Physical copies" value={fp.physical_copy_count} detail="Always 1 -- referenced, never duplicated (Phase 7)." />
                    <StatCard label="Estimated compute-unit-hours" value={fp.estimated_compute_unit_hours.toFixed(1)} />
                  </div>
                ) : (
                  <p>No footprint data.</p>
                )
              }
            </AsyncSection>
          </section>

          <section aria-labelledby="consumer-environments-heading" className="dashboard-section">
            <h2 id="consumer-environments-heading">Consumer environments</h2>
            <AsyncSection state={environmentRequests} loadingLabel="Loading environment requests">
              {(requests) => {
                const consumers = requests.filter((r) => r.current_version_id === datasetVersion.version_id);
                if (consumers.length === 0) {
                  return <p>No environment currently points at this version.</p>;
                }
                return (
                  <ul className="dashboard-section__list">
                    {consumers.map((request) => (
                      <li key={request.request_id}>
                        <Link to="/environments">{titleCase(request.environment)}</Link> — {request.consumer || "unlabeled consumer"} (next
                        refresh {formatDate(request.next_refresh_at)})
                      </li>
                    ))}
                  </ul>
                );
              }}
            </AsyncSection>
          </section>

          <section aria-labelledby="source-systems-heading" className="dashboard-section">
            <h2 id="source-systems-heading">Source systems</h2>
            <p>
              This platform&rsquo;s synthetic estate spans five simulated heterogeneous source systems; no artifact
              records which of them contributed rows to this specific dataset version (only per-entity row
              counts are tracked — see this page&rsquo;s module docstring). See the{" "}
              <Link to="/data-sources">Data Sources</Link> page for the full source-system breakdown from the
              data catalog.
            </p>
          </section>

          <section aria-labelledby="lineage-heading" className="dashboard-section">
            <h2 id="lineage-heading">Lineage</h2>
            <ol className="lineage-list">
              <li>Subset {subsetManifest.data ? `(${titleCase(subsetManifest.data.manifest.selection.strategy)})` : ""}</li>
              <li>
                Masked with policy {datasetVersion.masking_policy_name} v{datasetVersion.masking_policy_version}
              </li>
              {certification.data?.report.synthetic_generation_manifest_id && <li>Synthetic scenarios generated</li>}
              <li>
                Certified {certification.data ? `— ${certification.data.report.status}` : ""}
              </li>
              <li>Registered as dataset version v{datasetVersion.version_number}</li>
              <li>Requested into environments (see Consumer environments above)</li>
            </ol>
          </section>
        </>
      )}
    </AsyncSection>
  );
}
