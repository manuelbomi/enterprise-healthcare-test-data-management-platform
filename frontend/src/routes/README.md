# routes

Route definitions (React Router) mapping URL paths to page components in
`../pages` (Phase 9).

- `navigation.ts` -- the single source of truth for the left-nav
  structure/labels (`NAV_SECTIONS`), consumed by `../components/AppShell.tsx`.
- `index.tsx` -- the `createBrowserRouter` route table; every path here
  also appears in `navigation.ts`.
