/**
 * Honest "this isn't wired to a live API yet" placeholder, used only for
 * pages this phase deliberately does not fake data for (per the Phase 9
 * instructions: "Do not fake backend behavior if an implemented API
 * exists" — and, symmetrically, do not invent data when no API exists
 * either). See `problems_phase_09.md` for the per-page reasoning.
 */
export function NotYetAvailable({
  title,
  reason,
  roadmapPhase,
}: {
  title: string;
  reason: string;
  roadmapPhase?: string;
}) {
  return (
    <div className="not-yet-available">
      <h2>{title}</h2>
      <p>{reason}</p>
      {roadmapPhase && (
        <p className="not-yet-available__roadmap">
          See <code>ROADMAP.md</code> {roadmapPhase}.
        </p>
      )}
    </div>
  );
}
