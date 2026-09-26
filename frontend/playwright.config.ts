import { defineConfig, devices } from "@playwright/test";

/**
 * Playwright config for the TDM console's critical-workflow E2E tests
 * (`e2e/*.spec.ts`). Per the Phase 9 instructions ("do not fake backend
 * behavior if an implemented API exists"), these tests run against the
 * REAL control-plane API and REAL Vite dev server — never a mock server
 * — so this config deliberately does NOT spin up a `webServer` that
 * fakes anything; both real processes are started by the operator (or
 * CI job) first. See `docs/problems/problems_phase_09.md` for the exact two-step
 * startup sequence and the environment this was last verified in.
 *
 * Required before running `npm run test:e2e`:
 *
 *   1. Generate real demo data and start the control plane:
 *        python scripts/demo_phase9_console_data.py
 *        cd services/control-plane && uvicorn control_plane.main:app --port 8010
 *      (run from the repo root so the default `data/tmp/...` artifact
 *      paths resolve; see `control_plane/config.py`)
 *
 *   2. Start the frontend dev server pointed at that control plane:
 *        cd frontend
 *        VITE_API_BASE_URL=http://127.0.0.1:8010 npm run dev -- --port 5174
 *
 *   3. In a third shell: `npm run test:e2e` (or set `PLAYWRIGHT_BASE_URL`
 *      to point at a different already-running instance).
 */
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  retries: 0,
  reporter: [["list"]],
  use: {
    baseURL: process.env.PLAYWRIGHT_BASE_URL ?? "http://127.0.0.1:5174",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],
});
