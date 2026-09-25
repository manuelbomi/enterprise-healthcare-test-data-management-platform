"""Job entry points: thin, DAG-runnable wrappers around discovery,
subsetting, masking, and synthetic generation.

This module is the boundary the control plane's orchestrator actually
invokes (via the JobRequest/JobResult contract in libs/contracts) — it
translates a JobRequest into a call into the appropriate module above,
manages the Spark session lifecycle, and reports a JobResult back.

Phase 0 scope: placeholder module. Wired up in Phase 14 once the control
plane's orchestrator exists to call it.
"""
