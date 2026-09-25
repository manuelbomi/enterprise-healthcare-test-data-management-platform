import { syntheticApi } from "@/api";
import type { SyntheticManifestRecord } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatDate, formatNumber, titleCase } from "@/lib/format";

/**
 * Synthetic Data page. Backed by a real, new Phase 9 read-only endpoint
 * (`GET /api/v1/synthetic/manifests`,
 * `control_plane.artifacts.synthetic.SyntheticManifestRepository`) that
 * discovers every real `synthetic_generation_manifest.json` Phase 5's
 * scenario generator has written under the configured artifact root.
 * `DataProvenance` is surfaced explicitly per manifest -- the whole
 * point of Phase 5's provenance tagging is that a synthetic/negative-test
 * record is never mistaken for real (masked) data, so this page never
 * collapses that distinction.
 */
export function SyntheticDataPage() {
  const manifests = useApiData(() => syntheticApi.listSyntheticManifests());

  return (
    <>
      <PageHeader
        title="Synthetic Data"
        description="Real scenario-generation run history: which of the eleven required scenarios were generated, their data provenance, and row counts."
      />
      <AsyncSection state={manifests} loadingLabel="Loading synthetic generation manifests">
        {(records) => (
          <>
            <DataTable<SyntheticManifestRecord>
              caption={`${records.length} synthetic generation run(s) discovered on disk`}
              getRowKey={(row) => row.manifest.manifest_id}
              rows={records}
              emptyMessage="No synthetic generation manifests found under the configured artifact root. Run 'python -m data_plane.synthetic.cli' to produce one."
              columns={columns}
            />
            {records.map((record) => (
              <details key={record.manifest.manifest_id} className="masking-run-detail">
                <summary>
                  {record.manifest.mode} — {record.manifest.scenarios.length} scenario(s)
                </summary>
                <dl className="key-value-grid">
                  <dt>Source path</dt>
                  <dd>{record.source_path}</dd>
                  <dt>Base estate</dt>
                  <dd>{record.manifest.base_estate_dir ?? "None (standalone)"}</dd>
                  <dt>Scenarios</dt>
                  <dd>
                    <ul>
                      {record.manifest.scenarios.map((scenario) => (
                        <li key={scenario.scenario}>
                          {titleCase(scenario.scenario)} — provenance: <StatusBadge status={scenario.provenance} /> —{" "}
                          {formatNumber(Object.values(scenario.row_counts).reduce((t, c) => t + c, 0))} rows
                        </li>
                      ))}
                    </ul>
                  </dd>
                  <dt>Provenance row counts</dt>
                  <dd>
                    <ul>
                      {Object.entries(record.manifest.provenance_row_counts).map(([provenance, count]) => (
                        <li key={provenance}>
                          {titleCase(provenance)}: {formatNumber(count)}
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

const columns: DataTableColumn<SyntheticManifestRecord>[] = [
  { key: "mode", header: "Mode", render: (row) => titleCase(row.manifest.mode) },
  { key: "scenarios", header: "Scenarios", align: "right", render: (row) => formatNumber(row.manifest.scenarios.length) },
  { key: "created", header: "Created", render: (row) => formatDate(row.manifest.created_at) },
  {
    key: "total_rows",
    header: "Total rows",
    align: "right",
    render: (row) => formatNumber(Object.values(row.manifest.total_row_counts).reduce((t, c) => t + c, 0)),
  },
];
