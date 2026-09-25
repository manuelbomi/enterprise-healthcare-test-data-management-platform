# tdm-console (frontend)

The React + TypeScript + Vite console for requesting, inspecting, and
certifying test data. See `ARCHITECTURE.md` section 2.5 and
`docs/adr/0008-frontend-stack.md` at the repository root.

## Phase 9 status

A real, working, well-typed console. Thirteen route-mounted pages plus a
Dataset Detail page (see `src/pages/README.md`), a typed API client
layer (`src/api/`), Vitest + React Testing Library component tests, and
Playwright E2E tests for the critical workflows (Dashboard, Data
Catalog, Dataset Detail). See `problems_phase_09.md` (repository root)
for exactly which pages are backed by real live control-plane APIs vs.
honest "not yet available" placeholders, and why.

## Layout

```
src/
├── main.tsx        # Entry point
├── App.tsx          # Root shell -- mounts the router
├── pages/            # Route-mounted screens
├── components/         # Reusable presentational components
├── api/                  # Typed control-plane API client
├── hooks/                  # useApiData (loading/error/data state)
├── lib/                      # Formatting helpers
├── routes/                     # Route table + nav structure
└── test/                        # Vitest setup
e2e/                                # Playwright critical-workflow tests
```

## Local development

```bash
npm install
npm run dev        # start the Vite dev server (proxies /api to the control plane)
npm run lint         # ESLint, including jsx-a11y accessibility rules
npm run build          # tsc -b && vite build
npm run test              # Vitest component tests
npm run test:e2e            # Playwright E2E tests -- see playwright.config.ts's
                              # header comment for the required two-server startup
                              # sequence (real control plane + real Vite dev server,
                              # never a mock)
```

By default, the app talks to the control plane through the Vite dev
server's `/api` proxy (`vite.config.ts`), which targets
`http://localhost:8000`. Set `VITE_API_BASE_URL` (see `.env.example`) to
target a control plane running somewhere else instead (no code
changes needed) -- e.g. when a proxied port collides with something
else already running locally, or the control plane needs to run on a
different host, this requires the control plane to have CORS enabled
for the frontend's origin (`TDM_CONTROL_PLANE_CORS_ALLOWED_ORIGINS`,
see `services/control-plane/src/control_plane/config.py`).
