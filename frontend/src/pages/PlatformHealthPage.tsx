import { healthApi } from "@/api";
import { AsyncSection } from "@/components/AsyncSection";
import { PageHeader } from "@/components/PageHeader";
import { StatCard } from "@/components/StatCard";
import { useApiData } from "@/hooks/useApiData";

/**
 * Platform Health: wired to the real (if intentionally minimal) root
 * health endpoint (`GET /api/v1/health`, `api/v1/health.py`) --
 * liveness only, no downstream dependency checks yet. Full platform
 * integrity (resiliency, failure injection, a real `/ready` with
 * dependency checks) is `ROADMAP.md` Phase 11, not built yet; this page
 * shows exactly what exists today rather than a richer, fabricated
 * health dashboard.
 */
export function PlatformHealthPage() {
  const health = useApiData(() => healthApi.getHealth());

  return (
    <>
      <PageHeader
        title="Platform Health"
        description="Liveness only, from the real control-plane health endpoint. Full platform integrity (resiliency, failure injection, dependency-aware readiness) is ROADMAP.md Phase 11, not built yet."
      />
      <AsyncSection state={health} loadingLabel="Checking control-plane health">
        {(data) => (
          <div className="stat-grid">
            <StatCard label="Service" value={data.service} />
            <StatCard label="Status" value={data.status} tone={data.status === "ok" ? "good" : "critical"} />
          </div>
        )}
      </AsyncSection>
      <p className="callout callout--info">
        This is a liveness check only (the process is up and answering) — it does not check the database,
        the lifecycle scheduler, or any artifact directories. See <code>ROADMAP.md</code> Phase 11.
      </p>
    </>
  );
}
