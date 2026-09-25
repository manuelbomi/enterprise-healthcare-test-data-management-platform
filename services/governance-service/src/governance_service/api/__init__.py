"""RBAC / authorization decision endpoints.

Exposes the interface other planes call to ask "is this actor allowed to
perform this action on this subject" (see
libs/contracts for the eventual typed request/response shapes) and to
resolve secrets via the secrets provider adapter (see SECURITY.md).

Phase 0 scope: placeholder module. Implemented in Phase 3.
"""
