"""Tests for `control_plane.platform.retry.retry_with_backoff`."""

from __future__ import annotations

import pytest

from control_plane.platform.retry import RetriesExhaustedError, RetryPolicy, retry_with_backoff


def test_succeeds_on_first_attempt_without_sleeping() -> None:
    calls = []

    def fn() -> str:
        calls.append(1)
        return "ok"

    result = retry_with_backoff(fn, policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0))
    assert result == "ok"
    assert len(calls) == 1


def test_succeeds_after_transient_failures() -> None:
    attempts = {"count": 0}

    def flaky() -> str:
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise ConnectionError("transient")
        return "recovered"

    result = retry_with_backoff(flaky, policy=RetryPolicy(max_attempts=5, base_delay_seconds=0.0))
    assert result == "recovered"
    assert attempts["count"] == 3


def test_raises_retries_exhausted_after_max_attempts() -> None:
    attempts = {"count": 0}

    def always_fails() -> None:
        attempts["count"] += 1
        raise ConnectionError("still down")

    with pytest.raises(RetriesExhaustedError) as exc_info:
        retry_with_backoff(always_fails, policy=RetryPolicy(max_attempts=3, base_delay_seconds=0.0))
    assert attempts["count"] == 3
    assert isinstance(exc_info.value.__cause__, ConnectionError)


def test_max_attempts_one_means_no_retry() -> None:
    attempts = {"count": 0}

    def always_fails() -> None:
        attempts["count"] += 1
        raise RuntimeError("boom")

    with pytest.raises(RetriesExhaustedError):
        retry_with_backoff(always_fails, policy=RetryPolicy(max_attempts=1, base_delay_seconds=0.0))
    assert attempts["count"] == 1


def test_non_retryable_exception_propagates_immediately() -> None:
    attempts = {"count": 0}

    def fn() -> None:
        attempts["count"] += 1
        raise TypeError("not retryable")

    policy = RetryPolicy(max_attempts=3, base_delay_seconds=0.0, retry_on=(ConnectionError,))
    with pytest.raises(TypeError):
        retry_with_backoff(fn, policy=policy)
    assert attempts["count"] == 1


def test_invalid_max_attempts_rejected() -> None:
    with pytest.raises(ValueError):
        retry_with_backoff(lambda: None, policy=RetryPolicy(max_attempts=0))
