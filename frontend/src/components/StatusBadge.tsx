import { titleCase } from "@/lib/format";

export type BadgeTone = "neutral" | "good" | "warning" | "critical" | "info";

const TONE_BY_STATUS: Record<string, BadgeTone> = {
  // DatasetVersionStatus / EnvironmentRequestStatus
  active: "good",
  expired: "warning",
  revoked: "critical",
  rolled_back: "warning",
  paused: "warning",
  retired: "neutral",
  // CertificationStatus
  draft: "neutral",
  processing: "info",
  failed: "critical",
  certified: "good",
  published: "good",
  // IntegrityStatus
  passed: "good",
  passed_with_known_orphans: "warning",
};

/** Renders any of this platform's many lifecycle-status enum values
 * (`DatasetVersionStatus`, `CertificationStatus`, `IntegrityStatus`,
 * `EnvironmentRequestStatus`, ...) as a consistently-colored badge,
 * title-cased for readability. Falls back to `neutral` for an unknown
 * value rather than guessing. */
export function StatusBadge({ status }: { status: string }) {
  const tone = TONE_BY_STATUS[status] ?? "neutral";
  return <span className={`badge badge--${tone}`}>{titleCase(status)}</span>;
}

export function BooleanBadge({ value, trueLabel = "Yes", falseLabel = "No" }: { value: boolean; trueLabel?: string; falseLabel?: string }) {
  return <span className={`badge badge--${value ? "good" : "critical"}`}>{value ? trueLabel : falseLabel}</span>;
}
