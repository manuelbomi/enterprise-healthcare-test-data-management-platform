# components

Reusable, presentational UI components. Empty as of Phase 0. Every
component added here must be built accessible-by-default: semantic HTML
first, ARIA only where semantic HTML can't express the interaction, and
keyboard-navigable (see `docs/adr/0008-frontend-stack.md`). Components
should not fetch data themselves — data fetching belongs in `../api`,
called from `../pages`, with results passed down as props.
