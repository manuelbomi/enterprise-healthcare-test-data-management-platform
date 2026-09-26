# api

Typed client functions for calling the control plane's REST API
(`/api/v1/...`, proxied in local dev via `vite.config.ts`'s dev-server
proxy). This is the *only* place in the frontend that performs network
calls -- pages and components consume functions from here, never `fetch`
directly.

## Layout (Phase 9)

- `client.ts` -- the typed `fetch` wrapper (`apiGet`/`apiPost`/`apiPut`)
  and `ApiError`, which every domain module below is built on.
- `types.ts` -- hand-maintained TypeScript interfaces mirroring the
  Pydantic contracts in `libs/contracts/src/healthcare_tdm_contracts/`.
  Keeping these in sync is a Phase 19 contract-testing concern (see
  `docs/adr/0008-frontend-stack.md`).
- One module per control-plane domain: `catalog.ts` (Phase 2),
  `lifecycle.ts` (Phase 7), `capacity.ts` (Phase 8), and
  `masking.ts`/`subsetting.ts`/`synthetic.ts`/`certification.ts` (new,
  read-only Phase 9 endpoints -- see `docs/problems/problems_phase_09.md` for the
  per-domain decision to add these rather than fake their pages), plus
  `health.ts` (Phase 0).
- `index.ts` -- a barrel re-exporting every domain module as a
  namespace (`catalogApi`, `lifecycleApi`, ...) plus every type, so
  pages import from `@/api` rather than reaching into individual files.

Every function here calls a *real* control-plane endpoint. None of them
mock or fabricate data.
