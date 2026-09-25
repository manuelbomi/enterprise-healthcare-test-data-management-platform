import type { ReactNode } from "react";

export interface StatCardProps {
  label: string;
  value: ReactNode;
  detail?: ReactNode;
  tone?: "neutral" | "good" | "warning" | "critical";
}

/** A single dashboard metric tile. Semantic HTML (a `<dl>` term/definition
 * pair), not a styled `<div>` soup, so the label/value relationship is
 * conveyed to assistive technology without extra ARIA. */
export function StatCard({ label, value, detail, tone = "neutral" }: StatCardProps) {
  return (
    <dl className={`stat-card stat-card--${tone}`}>
      <dt className="stat-card__label">{label}</dt>
      <dd className="stat-card__value">{value}</dd>
      {detail && <dd className="stat-card__detail">{detail}</dd>}
    </dl>
  );
}
