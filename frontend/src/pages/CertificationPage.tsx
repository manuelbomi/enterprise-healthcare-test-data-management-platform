import { certificationApi } from "@/api";
import type { CertificationReportRecord } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatDate, titleCase } from "@/lib/format";

/**
 * Certification page. Backed by a real, new Phase 9 read-only endpoint
 * (`GET /api/v1/certification/reports`,
 * `control_plane.artifacts.certification.CertificationReportRepository`)
 * that discovers every real `certification_report.json` Phase 6's
 * certification pipeline has written -- including its enforced
 * six-state status lifecycle, the eleven independent gate results, and
 * (when present) the HMAC tamper-evidence signature. This is the
 * pipeline's own record, re-derived independently per gate rather than
 * trusting any earlier stage's own report -- see
 * `docs/CERTIFICATION_VS_MASKING.md`.
 */
export function CertificationPage() {
  const reports = useApiData(() => certificationApi.listCertificationReports());

  return (
    <>
      <PageHeader
        title="Certification"
        description="Real certification pipeline run history: status lifecycle, eleven independent gate results, and row-count reconciliation."
      />
      <AsyncSection state={reports} loadingLabel="Loading certification reports">
        {(records) => (
          <>
            <DataTable<CertificationReportRecord>
              caption={`${records.length} certification report(s) discovered on disk`}
              getRowKey={(row) => row.report.report_id}
              rows={records}
              emptyMessage="No certification reports found under the configured artifact root. Run 'python -m data_plane.certification.cli' to produce one."
              columns={columns}
            />
            {records.map((record) => (
              <details key={record.report.report_id} className="masking-run-detail">
                <summary>
                  {record.report.dataset_name} — {record.report.status.toUpperCase()}
                </summary>
                <dl className="key-value-grid">
                  <dt>Source path</dt>
                  <dd>{record.source_path}</dd>
                  <dt>Masking policy</dt>
                  <dd>
                    {record.report.masking_policy_name} v{record.report.masking_policy_version} (engine{" "}
                    {record.report.masking_engine_version})
                  </dd>
                  <dt>Signed</dt>
                  <dd>{record.report.integrity_signature ? "Yes (HMAC)" : "No — unsigned report"}</dd>
                  <dt>Gates</dt>
                  <dd>
                    <ul>
                      {record.report.gates.map((gate) => (
                        <li key={gate.gate}>
                          <span className={`badge badge--${gate.passed ? "good" : "critical"}`}>
                            {gate.passed ? "PASS" : "FAIL"}
                          </span>{" "}
                          {titleCase(gate.gate)} — {gate.detail}
                        </li>
                      ))}
                    </ul>
                  </dd>
                  <dt>Row count reconciliation</dt>
                  <dd>
                    <ul>
                      {Object.entries(record.report.row_count_reconciliation).map(([entity, trail]) => (
                        <li key={entity}>
                          {entity}: {trail}
                        </li>
                      ))}
                    </ul>
                  </dd>
                </dl>
              </details>
            ))}
          </>
        )}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<CertificationReportRecord>[] = [
  { key: "dataset", header: "Dataset", render: (row) => row.report.dataset_name },
  { key: "status", header: "Status", render: (row) => <StatusBadge status={row.report.status} /> },
  {
    key: "gates",
    header: "Gates passed",
    align: "right",
    render: (row) => `${row.report.gates.filter((g) => g.passed).length} / ${row.report.gates.length}`,
  },
  { key: "created", header: "Created", render: (row) => formatDate(row.report.created_at) },
  { key: "published", header: "Published", render: (row) => formatDate(row.report.published_at) },
];
