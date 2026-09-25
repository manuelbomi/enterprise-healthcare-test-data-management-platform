"""governance_service — RBAC, immutable audit events, secrets provider
adapter, and certification evidence.

See ARCHITECTURE.md section 2.4 and THREAT_MODEL.md (repository root).
This service owns trust: every other plane calls into it; it calls into
none of them (docs/adr/0003-plane-separation.md).
"""

__version__ = "0.1.0"
