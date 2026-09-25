# tdm-console (frontend)

The React + TypeScript + Vite console for requesting, inspecting, and
certifying test data. See `ARCHITECTURE.md` section 2.5 and
`docs/adr/0008-frontend-stack.md` at the repository root.

## Phase 0 status

Build/dev scaffold only — `package.json`, TypeScript config, ESLint/
Prettier config, and a placeholder `App` component so the pipeline is
proven out structurally. No real screens exist yet (see `ROADMAP.md`
Phase 16). `npm install` has not been run in this environment yet (tracked
as `P0-1` in `problems_master.md`).

## Layout

```
src/
├── main.tsx       # Entry point
├── App.tsx         # Root shell
├── pages/           # Route-mounted screens (Phase 16)
├── components/       # Reusable presentational components (Phase 16)
├── api/                # Typed control-plane API client (Phase 16)
└── routes/              # Route definitions (Phase 16)
```

## Local development (once dependencies are installed)

```bash
npm install
npm run dev       # start the Vite dev server
npm run lint       # ESLint, including jsx-a11y accessibility rules
npm run test        # Vitest unit tests
npm run test:e2e     # Playwright E2E tests (added once there are real screens)
```
