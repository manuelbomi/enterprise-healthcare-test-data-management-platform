"""A small, generic retry-with-backoff helper.

`THREAT_MODEL.md`'s control-plane "Tampering" mitigation already
assumes idempotency-keyed retries are safe; this module is the first
real, reusable implementation of that idea in this codebase, rather
than an ad hoc `for attempt in range(3)` loop duplicated wherever
retry logic is needed.

Deliberately generic (no job-type-specific knowledge) and deliberately
**not** wired into data-plane job execution (masking/subsetting/
certification) -- see `problems_phase_11.md` P11-6 for why: this
phase's own "masking job crashes halfway" failure-injection test
(P11-1) found that a mid-run crash can leave a partially-written
output directory with no atomicity guarantee. Blindly retrying a job
against the same output path in that state would risk making the
corruption worse (a second run's writes interleaving with the first
run's partial ones), not safer, until that gap is closed. Retrying is
safe for the one place this phase actually wires it in: the `/api/v1/ready`
endpoint's database connectivity check, a read-only, side-effect-free
operation where a transient connection failure is exactly the kind of
condition retrying is supposed to help with.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TypeVar

T = TypeVar("T")


@dataclass
class RetryPolicy:
    """Configuration for `retry_with_backoff`. `max_attempts=1` means
    "try once, never retry" -- a valid, explicit way to disable
    retrying for a given call site without a separate code path."""

    max_attempts: int = 3
    base_delay_seconds: float = 0.05
    backoff_multiplier: float = 2.0
    retry_on: Sequence[type[BaseException]] = field(default_factory=lambda: (Exception,))


class RetriesExhaustedError(RuntimeError):
    """Raised when every attempt failed. Wraps the last underlying
    exception (`__cause__`) rather than swallowing it -- a caller/log
    can always see the real, original failure."""


def retry_with_backoff(fn: Callable[[], T], *, policy: RetryPolicy | None = None) -> T:
    """Call `fn()` up to `policy.max_attempts` times, sleeping
    `base_delay_seconds * backoff_multiplier ** (attempt - 1)` between
    attempts, catching only the exception types in `policy.retry_on`
    (anything else propagates immediately -- retrying a
    programming-error exception, e.g. `TypeError`, would just waste
    time before failing anyway).

    Raises `RetriesExhaustedError` (chained to the last real exception)
    if every attempt fails. Returns `fn()`'s result on the first
    success.
    """

    policy = policy or RetryPolicy()
    if policy.max_attempts < 1:
        raise ValueError("policy.max_attempts must be >= 1")

    last_exc: BaseException | None = None
    for attempt in range(1, policy.max_attempts + 1):
        try:
            return fn()
        except tuple(policy.retry_on) as exc:  # noqa: PERF203 -- retry loop, not a hot path
            last_exc = exc
            if attempt == policy.max_attempts:
                break
            time.sleep(policy.base_delay_seconds * (policy.backoff_multiplier ** (attempt - 1)))

    raise RetriesExhaustedError(
        f"All {policy.max_attempts} attempt(s) failed; last error: {last_exc}"
    ) from last_exc


__all__ = ["RetriesExhaustedError", "RetryPolicy", "retry_with_backoff"]
