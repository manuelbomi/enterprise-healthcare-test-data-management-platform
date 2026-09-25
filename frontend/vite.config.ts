import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import path from "node:path";

// See ARCHITECTURE.md section 2.5 and docs/adr/0008-frontend-stack.md for
// why this app is built with React + TypeScript + Vite, and why it talks
// only to the control-plane REST API (never directly to storage, the
// metadata database, or Spark).
export default defineConfig({
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
      // the frontend never needs to hardcode a cross-origin URL. The
      // control plane's actual host/port is finalized in Phase 2.
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
