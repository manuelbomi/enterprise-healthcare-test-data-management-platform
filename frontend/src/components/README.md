# components

Reusable, presentational UI components (Phase 9). Every component here
is built accessible-by-default: semantic HTML first, ARIA only where
semantic HTML can't express the interaction, and keyboard-navigable (see
`docs/adr/0008-frontend-stack.md`). Components do not fetch data
themselves -- data fetching belongs in `../api`/`../hooks`, called from
`../pages`, with results passed down as props or via `AsyncSection`.

## Inventory

- `AppShell.tsx` -- root layout: skip link, primary navigation
  (`../routes/navigation.ts`), and the routed `<Outlet>`.
- `AsyncSection.tsx` -- renders the loading/error/data states of a
  `useApiData` result consistently across every page.
- `LoadingState.tsx` / `ErrorState.tsx` -- accessible loading and error
  presentation; `ErrorState` distinguishes the platform's well-known
  HTTP 503 "artifact not generated yet" condition (ADR-0009) from other
  failures.
- `NotYetAvailable.tsx` -- the honest "no backing API yet" placeholder
  used only by `AuditTrailPage` (Phase 13).
- `StatCard.tsx` / `StatusBadge.tsx` / `DataTable.tsx` / `PageHeader.tsx`
  -- the small set of presentational primitives every page composes.

See each component's own `*.test.tsx` for its component tests (Vitest +
React Testing Library).
