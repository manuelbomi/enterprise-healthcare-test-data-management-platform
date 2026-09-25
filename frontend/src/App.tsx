/**
 * Root application shell.
 *
 * Phase 0 scope: a placeholder screen only, confirming the build/dev
 * pipeline works. Real screens (snapshot request form, job status,
 * classification review, certification evidence viewer) are added
 * starting Phase 16, once the control-plane API they depend on exists.
 *
 * See ARCHITECTURE.md section 2.5 and docs/adr/0008-frontend-stack.md:
 * this app talks only to the control-plane REST API under /api — never
 * directly to storage, the metadata database, or Spark.
 */
export default function App() {
  return (
    <main>
      <h1>Enterprise Healthcare Test Data Management Platform</h1>
      <p>
        This console is not implemented yet — Phase 0 established only the
        project scaffold. See <code>ROADMAP.md</code> for the build plan.
      </p>
    </main>
  );
}
