# pages

Top-level, route-mounted screens (e.g., "Request a snapshot", "Job status",
"Classification review", "Certification evidence"). Empty as of Phase 0 —
populated starting Phase 16, once the control-plane API endpoints these
screens depend on exist. A page component composes smaller components from
`../components`; it should not itself contain business logic beyond
fetching data via `../api` and handling page-level state.
