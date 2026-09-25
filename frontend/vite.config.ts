import { configDefaults, defineConfig } from "vitest/config";
import { loadEnv } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// See ARCHITECTURE.md section 2.5 and docs/adr/0008-frontend-stack.md for
// why this app is built with React + TypeScript + Vite, and why it talks
// only to the control-plane REST API (never directly to storage, the
// metadata database, or Spark).
export default defineConfig(({ mode }) => {
  // Read from `.env`/`.env.local` (and real process env, which still
  // wins) via Vite's own loader rather than a bare `process.env` read --
  // this is the documented, reliable way to pick up a non-`VITE_`-
  // prefixed override for a *server-side* config value (the dev-proxy
  // target below is Node-side config, never shipped to the browser, so
  // it deliberately isn't `VITE_`-prefixed).
  const env = loadEnv(mode, process.cwd(), "");

  return {
    plugins: [react()],
    resolve: {
      alias: {
        "@": path.resolve(__dirname, "./src"),
      },
    },
    server: {
      port: 5173,
      proxy: {
        // Local dev convenience: proxy API calls to the control plane so
        // the frontend never needs to hardcode a cross-origin URL (and
        // never needs the control plane to enable CORS -- see
        // src/api/README.md). `CONTROL_PLANE_PROXY_TARGET` (set via
        // `.env.local` or the environment) lets a verification/E2E run
        // point this at a control plane running on a non-default port
        // without editing this file -- see `playwright.config.ts`'s
        // header comment.
        "/api": {
          target: env.CONTROL_PLANE_PROXY_TARGET || "http://localhost:8000",
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: true,
      // `e2e/` holds Playwright specs (a different `test()` API, run by
      // `npm run test:e2e` / `playwright.config.ts`) -- excluded here so
      // `npm run test` (Vitest) never tries to collect them.
      exclude: [...configDefaults.exclude, "e2e/**"],
    },
  };
});
