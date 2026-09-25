"""Readiness checks -- distinct from the Phase 0 liveness-only `/api/v1/health`.

Phase 0's `health.py` module docstring was explicit about the gap this
module fills: "/health ... deliberately does not check downstream
dependencies (database, storage) -- that is the job of /ready, added
once this service has real dependencies to check." Phase 7 gave this
service its first real dependency (the lifecycle database); this phase
finally adds the readiness check Phase 0 promised.

Liveness (`/health`) answers "is the process up and able to respond at
all" -- a load balancer/orchestrator uses it to decide whether to
restart the process. Readiness (`/ready`) answers "can this process
currently serve real traffic" -- an orchestrator uses it to decide
whether to route traffic to this instance right now. A process can be
alive but not ready (e.g. its database is temporarily unreachable) --
conflating the two (as a single `/health` endpoint that also pings the
database would) means a transient DB blip causes the orchestrator to
kill and restart a perfectly healthy process, instead of just pausing
traffic to it until the dependency recovers.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.engine import Engine

from control_plane.platform.retry import RetryPolicy, RetriesExhaustedError, retry_with_backoff


@dataclass
class ReadinessCheckResult:
    """The outcome of one readiness check."""

    name: str
    healthy: bool
    required: bool
    detail: str


def check_database(engine: Engine, *, retry_policy: RetryPolicy | None = None) -> ReadinessCheckResult:
    """Confirm the lifecycle database (Phase 7's `control_plane.db.models`
    schema) is actually reachable -- not just that `Settings.lifecycle_database_url`
    is *configured*, which `/health` could already tell you without
    opening a connection.

    Retries transient failures (`control_plane.platform.retry`) before
    reporting unhealthy -- a single failed `SELECT 1` due to a
    momentary connection blip should not flip readiness off and cause
    an orchestrator to pull traffic; a database that is *actually*
    down should.
    """

    def _ping() -> None:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))

    try:
        retry_with_backoff(_ping, policy=retry_policy or RetryPolicy(max_attempts=3, base_delay_seconds=0.02))
    except RetriesExhaustedError as exc:
        return ReadinessCheckResult(
            name="database",
            healthy=False,
            required=True,
            # Deliberately does not include the raw exception's full
            # text unmodified -- a real DB driver exception can embed
            # the connection string (including credentials in a
            # production deployment). Only the exception's type name
            # is reported; see THREAT_MODEL.md's control-plane
            # "Information disclosure" mitigation ("documented error
            # contract that never echoes raw data details").
            detail=f"database unreachable after retries ({type(exc.__cause__).__name__ if exc.__cause__ else 'error'})",
        )
    return ReadinessCheckResult(name="database", healthy=True, required=True, detail="reachable")


def check_catalog_artifact(catalog_path: Path) -> ReadinessCheckResult:
    """Confirm the Phase 2 catalog JSON artifact (ADR-0009) exists on
    disk. Marked `required=False`: a freshly stood-up control plane
    with no discovery run yet is a legitimate, if incomplete, state --
    `/api/v1/catalog` already reports this honestly
    (`CatalogNotAvailableError` -> 503) rather than crashing, so this
    check is informational for an operator, not a hard readiness gate.
    """

    if catalog_path.exists():
        return ReadinessCheckResult(name="catalog_artifact", healthy=True, required=False, detail="present")
    return ReadinessCheckResult(
        name="catalog_artifact",
        healthy=False,
        required=False,
        detail=f"not found at {catalog_path} (run the discovery CLI, or ignore if not needed yet)",
    )


def evaluate_readiness(
    *, engine: Engine, catalog_path: Path
) -> tuple[bool, list[ReadinessCheckResult]]:
    """Run every readiness check and return `(overall_ready, checks)`.
    `overall_ready` is `False` iff any *required* check is unhealthy --
    an unhealthy optional check (e.g. no catalog yet) is reported but
    does not by itself fail readiness."""

    checks = [check_database(engine), check_catalog_artifact(catalog_path)]
    overall = all(c.healthy for c in checks if c.required)
    return overall, checks


__all__ = ["ReadinessCheckResult", "check_catalog_artifact", "check_database", "evaluate_readiness"]
