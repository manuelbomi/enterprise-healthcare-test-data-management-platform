/** Accessible loading indicator: `role="status"` + visually-hidden text
 * so a screen reader announces "Loading" without a sighted user needing
 * a spinner graphic. See `docs/adr/0008-frontend-stack.md` (accessible
 * by default, semantic HTML first). */
export function LoadingState({ label = "Loading" }: { label?: string }) {
  return (
    <p className="loading-state" role="status">
      <span className="visually-hidden">{label}…</span>
      <span aria-hidden="true">{label}…</span>
    </p>
  );
}
