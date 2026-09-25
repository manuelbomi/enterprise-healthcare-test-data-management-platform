# api

Typed client functions for calling the control plane's REST API
(`/api/v1/...`, proxied in local dev — see `vite.config.ts`). Empty as of
Phase 0. TypeScript types used here should mirror the Pydantic contracts
in `libs/contracts`; keeping these in sync is tracked as a contract-testing
concern for Phase 19 (see `docs/adr/0008-frontend-stack.md`). This is the
*only* place in the frontend that should perform network calls — pages and
components consume functions from here, never `fetch` directly.
