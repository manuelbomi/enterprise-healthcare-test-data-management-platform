/**
 * Vitest global test setup: extends `expect` with jest-dom matchers
 * (`toBeInTheDocument`, `toHaveTextContent`, ...) for every component
 * test in `src/**\/*.test.tsx`. Registered via `vite.config.ts`'s
 * `test.setupFiles`.
 */
import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// @testing-library/react's automatic post-test DOM cleanup relies on a
// global `afterEach` (registered via `vitest/globals`). This project
// deliberately keeps `test.globals` off (see `vite.config.ts`) so test
// files import `describe`/`it`/`expect` explicitly -- so cleanup is
// wired up explicitly here instead, once, for every test file.
afterEach(() => {
  cleanup();
});
