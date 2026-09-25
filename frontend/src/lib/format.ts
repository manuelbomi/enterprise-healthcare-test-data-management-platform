/** Small, dependency-free formatting helpers shared across pages. Kept
 * here (not duplicated per-page) because this console renders the same
 * byte/count/date shapes in a dozen places (Dashboard tiles, Dataset
 * Detail, Capacity & Cost, ...). */

/** Format a byte count using decimal (1000-based) units, matching
 * `libs/contracts.capacity.TERABYTE_BYTES`'s decimal-TB convention. */
export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes)) return "—";
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB", "PB"];
  // Division-by-1000 loop rather than `Math.floor(Math.log10(bytes) / 3)`:
  // floating-point error makes `Math.log10(1000)` evaluate to
  // 2.9999999999999996 in JS, which floors to the WRONG exponent (0
  // instead of 1) for exact powers of 1000 -- caught by
  // `formatBytes.test.ts`'s `formatBytes(1000)` case.
  let exponent = 0;
  let value = Math.abs(bytes);
  while (value >= 1000 && exponent < units.length - 1) {
    value /= 1000;
    exponent += 1;
  }
  const signed = bytes < 0 ? -value : value;
  return `${signed.toFixed(exponent === 0 ? 0 : 2)} ${units[exponent]}`;
}

export function formatNumber(value: number): string {
  if (!Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatPercent(fraction: number, digits = 1): string {
  if (!Number.isFinite(fraction)) return "—";
  return `${(fraction * 100).toFixed(digits)}%`;
}

export function formatDate(iso: string | null | undefined): string {
  if (!iso) return "—";
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return new Intl.DateTimeFormat("en-US", {
    year: "numeric",
    month: "short",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(date);
}

export function formatRelativeToNow(iso: string | null | undefined): string {
  if (!iso) return "—";
  const target = new Date(iso).getTime();
  if (Number.isNaN(target)) return iso;
  const diffMs = target - Date.now();
  const diffDays = Math.round(diffMs / (1000 * 60 * 60 * 24));
  if (diffDays === 0) return "today";
  if (diffDays > 0) return `in ${diffDays} day${diffDays === 1 ? "" : "s"}`;
  return `${Math.abs(diffDays)} day${Math.abs(diffDays) === 1 ? "" : "s"} ago`;
}

/** Title-cases a snake_case enum value for display, e.g.
 * `hmac_pseudonymization` -> `Hmac Pseudonymization`. */
export function titleCase(value: string): string {
  return value
    .split(/[_\s]+/)
    .filter(Boolean)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export function sum(values: number[]): number {
  return values.reduce((total, value) => total + value, 0);
}
