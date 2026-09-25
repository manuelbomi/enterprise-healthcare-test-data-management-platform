"""Immutable audit event log.

Appends AuditEvent records (see
libs/contracts/src/healthcare_tdm_contracts/audit.py) to durable,
append-only storage. The application layer intentionally exposes no
update or delete path for these records (see SECURITY.md, "Immutable
audit evidence" and THREAT_MODEL.md, Repudiation).

Phase 0 scope: placeholder module. Implemented in Phase 3. Design intent:
backed by an append-only table pattern in PostgreSQL (no UPDATE/DELETE
grants for the application role) as the default, with the interface kept
narrow enough that a future move to a dedicated immutable log technology
would not require changes to callers.
"""
