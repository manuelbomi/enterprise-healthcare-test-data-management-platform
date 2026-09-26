"""Immutable audit event log.

Appends AuditEvent records (see
libs/contracts/src/healthcare_tdm_contracts/audit.py) to durable,
append-only storage. The application layer intentionally exposes no
update or delete path for these records (see SECURITY.md, "Immutable
audit evidence" and THREAT_MODEL.md, Repudiation).

Phase 0 scope: placeholder module -- not yet implemented here. Audit
logging was actually built in Phase 11, but inside
`services/control-plane` (`control_plane.platform.audit`), not here,
per ADR-0015/ADR-0016 -- `services/governance-service` remains a
scaffold with no running application logic of its own (see
`ARCHITECTURE.md` section 2.4 for the same explanation aimed at a
reader of that file, and `problems_final_review.md` P2-11, which this
docstring update resolves: an earlier version of this docstring said
"Implemented in Phase 3," which was never true in either direction --
audit logging was never built in this service in Phase 3 or any other
phase, and Phase 3 is masking, an unrelated capability). Design intent
if this service is ever activated for real: an append-only table
pattern in PostgreSQL (no UPDATE/DELETE grants for the application
role) as the default, with the interface kept narrow enough that a
future move to a dedicated immutable log technology would not require
changes to callers -- see `control_plane.platform.audit`'s own module
docstring for the real, implemented version of that same design intent.
"""
