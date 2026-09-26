"""Real, minimal structured logging (Phase 18A, resolves
`problems_final_review.md` P1-5: "`ARCHITECTURE.md`'s observability
claim is unimplemented; zero logging/metrics/tracing infrastructure
anywhere; `log_level` config is dead code").

**What this module makes real**: every HTTP request this service
handles now emits one structured (JSON) log line, actually configured
from `control_plane.config.Settings.log_level` (previously validated at
startup but never read by anything -- see `config.py`'s own history),
tagged with a correlation ID that is generated per request (or
propagated from an `X-Correlation-Id` request header, so a caller
integrating with this service can thread its own trace ID through) and
echoed back on the response so a client can correlate its own logs with
this service's.

**What this module deliberately does NOT build** (see
`ARCHITECTURE.md` section 3.3's Phase 18A note): real distributed
tracing (OpenTelemetry spans crossing control plane -> data plane ->
metadata plane) and real metrics emission (Prometheus/StatsD counters
and histograms) are NOT implemented here. Building a correlation-ID
mechanism that *looks* like a trace without a real trace collector, or
a metrics-shaped log line without a real metrics backend to scrape it,
would be exactly the kind of "looks real without the infrastructure to
back it" this repository's own `docs/adr/0012-refresh-orchestration-abstraction.md`
already warns against for a different capability. A correlation ID
threaded through structured logs is the honest, proportionate middle
ground: real, useful for correlating one request's log lines by hand or
with a log-aggregation tool that already exists (e.g. grepping/`jq`-ing
JSON lines, or feeding them into any real log platform), but it is not
a distributed trace and this module does not claim otherwise.
"""

from __future__ import annotations

import json
import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import TextIO

#: The stdlib `logging.LogRecord` attributes every record has by
#: construction -- excluded when merging a record's `extra=` fields
#: into the JSON payload, so only caller-supplied structured context
#: (correlation_id, method, path, status_code, duration_ms, ...) is
#: added on top of the fixed fields `JsonFormatter` always emits.
_STANDARD_LOGRECORD_ATTRS = frozenset(
    {
        "name",
        "msg",
        "args",
        "levelname",
        "levelno",
        "pathname",
        "filename",
        "module",
        "exc_info",
        "exc_text",
        "stack_info",
        "lineno",
        "funcName",
        "created",
        "msecs",
        "relativeCreated",
        "thread",
        "threadName",
        "processName",
        "process",
        "taskName",
        "message",
    }
)

#: The correlation ID for the request currently being handled on this
#: task/thread -- set by `main.py`'s request-logging middleware at the
#: start of every request, read by `JsonFormatter` for every log line
#: emitted while handling it (so a handler/repository function that
#: just calls `logging.getLogger(__name__).info(...)` with no `extra=`
#: still gets a correlation-ID-tagged log line for free).
_correlation_id: ContextVar[str] = ContextVar("control_plane_correlation_id", default="-")


def new_correlation_id() -> str:
    return uuid.uuid4().hex


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(value: str) -> None:
    _correlation_id.set(value)


class JsonFormatter(logging.Formatter):
    """Renders one `logging.LogRecord` as one JSON line: `timestamp`,
    `level`, `logger`, `message`, `correlation_id`, plus whatever
    additional structured fields the call site passed via `extra=`."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": getattr(record, "correlation_id", None) or _correlation_id.get(),
        }
        for key, value in record.__dict__.items():
            if key in _STANDARD_LOGRECORD_ATTRS or key in payload:
                continue
            payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


_configured = False


def configure_logging(level: str = "INFO", *, stream: TextIO | None = None) -> None:
    """Configure the root logger to emit one JSON line per record at
    `stream` (default `sys.stdout`), at `level` -- the first real
    consumer of `Settings.log_level` this service has ever had. Safe to
    call more than once (idempotent -- replaces, rather than
    accumulates, handlers, so calling it again with a different level
    -- e.g. in a test -- does not double-log)."""

    global _configured
    root = logging.getLogger()
    root.setLevel(level)
    handler = logging.StreamHandler(stream if stream is not None else sys.stdout)
    handler.setFormatter(JsonFormatter())
    root.handlers = [handler]
    _configured = True


def is_configured() -> bool:
    return _configured


__all__ = [
    "JsonFormatter",
    "configure_logging",
    "get_correlation_id",
    "is_configured",
    "new_correlation_id",
    "set_correlation_id",
]
