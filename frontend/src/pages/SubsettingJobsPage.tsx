import { subsettingApi } from "@/api";
import type { SubsetManifestRecord } from "@/api/types";
import { AsyncSection } from "@/components/AsyncSection";
import { DataTable, type DataTableColumn } from "@/components/DataTable";
import { PageHeader } from "@/components/PageHeader";
import { StatusBadge } from "@/components/StatusBadge";
import { useApiData } from "@/hooks/useApiData";
import { formatBytes, formatDate, formatNumber, titleCase } from "@/lib/format";

/**
 * Subsetting Jobs page. Backed by a real, new Phase 9 read-only
 * endpoint (`GET /api/v1/subsetting/manifests`,
 * `control_plane.artifacts.subsetting.SubsetManifestRepository`) that
 * discovers every real `subset_manifest.json` Phase 4's subsetting
 * engine has written under the configured artifact root.
 */
export function SubsettingJobsPage() {
  const manifests = useApiData(() => subsettingApi.listSubsetManifests());

  return (
    <>
      <PageHeader
        title="Subsetting Jobs"
        description="Real subsetting-engine run history: which sizing strategy selected how many rows per entity, referential-integrity status, and relationship-graph edges traversed."
      />
      <AsyncSection state={manifests} loadingLabel="Loading subsetting manifests">
        {(records) => (
          <>
            <DataTable<SubsetManifestRecord>
              caption={`${records.length} subsetting run(s) discovered on disk`}
              getRowKey={(row) => row.manifest.manifest_id}
              rows={records}
              emptyMessage="No subset manifests found under the configured artifact root. Run 'python -m data_plane.subsetting.cli' to produce one."
              columns={columns}
            />
            {records.map((record) => (
              <details key={record.manifest.manifest_id} className="masking-run-detail">
                <summary>
                  {record.manifest.selection.strategy} — {record.manifest.selection.description || record.source_path}
                </summary>
                <dl className="key-value-grid">
                  <dt>Source path</dt>
                  <dd>{record.source_path}</dd>
                  <dt>Scale profile</dt>
                  <dd>{record.manifest.scale_profile}</dd>
                  <dt>Row counts (source → selected)</dt>
                  <dd>
                    <ul>
                      {Object.entries(record.manifest.selected_counts).map(([entity, selected]) => (
                        <li key={entity}>
                          {entity}: {formatNumber(record.manifest.source_counts[entity] ?? 0)} → {formatNumber(selected)}
                        </li>
                      ))}
                    </ul>
                  </dd>
                  <dt>Relationship edges traversed</dt>
                  <dd>
                    <ul>
                      {record.manifest.relationship_edges.map((edge) => (
                        <li key={`${edge.parent_entity}-${edge.child_entity}`}>
                          {edge.parent_entity} → {edge.child_entity}: {formatNumber(edge.edge_count)}
                        </li>
                      ))}
                    </ul>
                  </dd>
                  {record.manifest.integrity_findings.length > 0 && (
                    <>
                      <dt>Integrity findings</dt>
                      <dd>
                        <ul>
                          {record.manifest.integrity_findings.map((finding) => (
                            <li key={finding}>{finding}</li>
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

const columns: DataTableColumn<SubsetManifestRecord>[] = [
  { key: "strategy", header: "Strategy", render: (row) => titleCase(row.manifest.selection.strategy) },
  { key: "scale", header: "Scale profile", render: (row) => row.manifest.scale_profile },
  { key: "created", header: "Created", render: (row) => formatDate(row.manifest.created_at) },
  {
    key: "integrity",
    header: "Integrity",
    render: (row) => <StatusBadge status={row.manifest.integrity_status} />,
  },
  { key: "storage", header: "Subset storage (est.)", align: "right", render: (row) => formatBytes(row.manifest.estimated_subset_storage_bytes) },
];
