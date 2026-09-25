"""Domain layer: orchestration and policy logic.

This is where control-plane business logic lives — job DAG construction,
policy resolution, capacity/quota checks. Code here must not perform I/O
directly against a specific database driver or HTTP client; it depends on
narrow interfaces (repositories, clients) so it stays unit-testable
without a running Postgres/network. Concrete I/O implementations live in
`control_plane.db` and future `control_plane.clients` modules.

Phase 0 scope: this module is an empty placeholder establishing where
orchestration/policy code will live starting Phase 2 (orchestration) and
Phase 14 (job DAG execution).
"""
