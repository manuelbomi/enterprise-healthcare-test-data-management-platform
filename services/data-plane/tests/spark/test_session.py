"""Tests for `data_plane.spark.session` -- the local `SparkSession`
builder and the Windows native-shim (`winutils.exe`/`HADOOP_HOME`)
resolution logic.

The Windows-specific tests monkeypatch `sys.platform` so they run (and
mean something) on whatever platform CI/this repository's own tests
actually execute on, per this module's own honesty conventions: this
repository's real CI runs on `ubuntu-latest`
(`.github/workflows/ci.yml`), where none of this logic is exercised for
real, so it must be exercised under a simulated platform instead of
silently being untested everywhere but a developer's own Windows laptop.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from pyspark.sql import SparkSession

from data_plane.spark.session import (
    DEFAULT_SHUFFLE_PARTITIONS,
    HADOOP_RUNTIME_ENV_VAR,
    MissingWindowsHadoopRuntimeError,
    configure_windows_hadoop_runtime,
)


def test_local_session_runs_a_trivial_job(spark: SparkSession) -> None:
    assert spark.range(5).count() == 5


def test_local_session_uses_small_default_shuffle_partitions(spark: SparkSession) -> None:
    assert spark.conf.get("spark.sql.shuffle.partitions") == str(DEFAULT_SHUFFLE_PARTITIONS)


@pytest.fixture
def clean_hadoop_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HADOOP_HOME", raising=False)
    monkeypatch.delenv(HADOOP_RUNTIME_ENV_VAR, raising=False)
    # `configure_windows_hadoop_runtime` mutates HADOOP_HOME/PATH directly
    # (not via monkeypatch) when it finds a runtime -- registering PATH's
    # current value with monkeypatch here still gets it restored at
    # teardown, even though the mutation in between bypasses monkeypatch.
    monkeypatch.setenv("PATH", os.environ.get("PATH", ""))


def test_configure_windows_hadoop_runtime_is_noop_off_windows(
    monkeypatch: pytest.MonkeyPatch, clean_hadoop_env: None
) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    assert configure_windows_hadoop_runtime(search_dirs=[]) is None
    assert "HADOOP_HOME" not in os.environ


def test_configure_windows_hadoop_runtime_finds_cached_runtime(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_hadoop_env: None
) -> None:
    runtime_bin = tmp_path / ".spark-runtime" / "hadoop-9.9.9" / "bin"
    runtime_bin.mkdir(parents=True)
    (runtime_bin / "winutils.exe").write_bytes(b"not a real binary")

    monkeypatch.setattr(sys, "platform", "win32")
    resolved = configure_windows_hadoop_runtime(search_dirs=[tmp_path])

    assert resolved == str(runtime_bin.parent)
    assert os.environ["HADOOP_HOME"] == str(runtime_bin.parent)
    assert str(runtime_bin) in os.environ["PATH"].split(os.pathsep)


def test_configure_windows_hadoop_runtime_raises_when_not_found(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_hadoop_env: None
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    with pytest.raises(MissingWindowsHadoopRuntimeError):
        configure_windows_hadoop_runtime(search_dirs=[tmp_path])


def test_configure_windows_hadoop_runtime_honors_env_var_override(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, clean_hadoop_env: None
) -> None:
    override_bin = tmp_path / "custom-hadoop" / "bin"
    override_bin.mkdir(parents=True)
    (override_bin / "winutils.exe").write_bytes(b"not a real binary")

    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv(HADOOP_RUNTIME_ENV_VAR, str(override_bin.parent))

    resolved = configure_windows_hadoop_runtime(search_dirs=[])
    assert resolved == str(override_bin.parent)
    assert os.environ["HADOOP_HOME"] == str(override_bin.parent)


def test_configure_windows_hadoop_runtime_is_idempotent_when_already_set(
    monkeypatch: pytest.MonkeyPatch, clean_hadoop_env: None
) -> None:
    monkeypatch.setattr(sys, "platform", "win32")
    monkeypatch.setenv("HADOOP_HOME", "/already/configured")
    assert configure_windows_hadoop_runtime(search_dirs=[]) == "/already/configured"
