"""Job entry points: thin, DAG-runnable wrappers around discovery,
subsetting, masking, and synthetic generation.

This module is the boundary the control plane's orchestrator actually
invokes (via the JobRequest/JobResult contract in libs/contracts) — it
translates a JobRequest into a call into the appropriate module above,
manages the Spark session lifecycle, and reports a JobResult back.

Phase 0 scope: placeholder module, originally expected to be wired up in
Phase 14. Phase 14's actual scope turned out to be scale/performance
benchmark tooling (`data_plane.spark`, `data_plane.benchmarks`), not
job-orchestration wiring -- this module remains an unwired placeholder;
see `problems_phase_14.md` P14-4 and `services/data-plane/README.md`'s
"Status" section for the honest, corrected account.
"""
