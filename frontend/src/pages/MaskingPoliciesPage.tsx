import { maskingApi } from "@/api";
import type { MaskingRunRecord } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { useApiData } from "@/hooks/useApiData";
import { formatNumber, titleCase } from "@/lib/format";

/**
 * Masking Policies page. Backed by a real, new Phase 9 read-only
 * endpoint (`GET /api/v1/masking/runs`,
 * `control_plane.artifacts.masking.MaskingRunRepository`) that
 * discovers every real `masking_run_summary.json` Phase 3's masking
 * engine has written under the configured artifact root -- see
 * `problems_phase_09.md` for why this page shows *masking run history*
 * (what the engine actually did) rather than a *policy editor*: the
 * authoritative policy definition
 * (`data_plane.masking.policy.DEFAULT_POLICY`) is data-plane source
 * code, not yet a control-plane-managed/versioned resource a UI could
 * edit -- that is out of this phase's honest scope.
 */
export function MaskingPoliciesPage() {
  const runs = useApiData(() => maskingApi.listMaskingRuns());

  return (
    <>
      <PageHeader
        title="Masking Policies"
        description="Real masking engine run history: what technique masked how many columns, and whether the run's own referential-integrity/leakage validation passed. See problems_phase_09.md for why this page shows run history rather than a policy editor."
      />
      <AsyncSection state={runs} loadingLabel="Loading masking runs">
        {(records) => (
          <>
            <DataTable<MaskingRunRecord>
              caption={`${records.length} masking run(s) discovered on disk`}
              getRowKey={(row) => row.source_path}
              rows={records}
              emptyMessage="No masking runs found under the configured artifact root. Run 'python -m data_plane.masking.cli' to produce one."
              columns={columns}
            />
            {records.map((record) => (
              <details key={record.source_path} className="masking-run-detail">
                <summary>{record.source_path}</summary>
                <dl className="key-value-grid">
                  <dt>Masking engine version</dt>
                  <dd>{record.summary.masking_engine_version || "—"}</dd>
                  <dt>Policy</dt>
                  <dd>
                    {record.summary.policy_name ?? "—"} v{record.summary.policy_version ?? "—"}
                  </dd>
                  <dt>Technique breakdown</dt>
                  <dd>
                    <ul>
                      {Object.entries(record.summary.technique_counts).map(([technique, count]) => (
                        <li key={technique}>
                          {titleCase(technique)}: {formatNumber(count)}
                        </li>
                      ))}
                    </ul>
                  </dd>
                  {record.summary.validation_failures.length > 0 && (
                    <>
                      <dt>Validation failures</dt>
                      <dd>
                        <ul>
                          {record.summary.validation_failures.map((failure) => (
                            <li key={failure}>{failure}</li>
                          ))}
                        </ul>
                      </dd>
                    </>
                  )}
                </dl>
              </details>
            ))}
          </>
        )}
      </AsyncSection>
    </>
  );
}

const columns: DataTableColumn<MaskingRunRecord>[] = [
  { key: "source", header: "Run", render: (row) => row.source_path.split(/[\\/]/).slice(-2).join("/") },
  { key: "rows", header: "Rows processed", align: "right", render: (row) => formatNumber(row.summary.rows_processed) },
  { key: "columns", header: "Column-values masked", align: "right", render: (row) => formatNumber(row.summary.columns_masked) },
  { key: "warnings", header: "Warnings", align: "right", render: (row) => formatNumber(row.summary.warning_count) },
  {
    key: "validation",
    header: "Validation",
    render: (row) => (
      <span className={`badge badge--${row.summary.validation_passed ? "good" : "critical"}`}>
        {row.summary.validation_passed ? "Passed" : "Failed"}
      </span>
    ),
  },
];
