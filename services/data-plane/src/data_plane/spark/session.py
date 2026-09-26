"""Local PySpark session construction (Phase 14).

This is the *only* file in `data_plane` that builds a `SparkSession` --
every caller (`data_plane.spark.masking_job`,
`data_plane.spark.subsetting_job`, `data_plane.benchmarks`, tests) gets
one from `get_local_spark_session`, never by calling
`SparkSession.builder` directly. That keeps session configuration (local
parallelism, shuffle-partition count, the Windows native-shim workaround
below) a single-responsibility concern, exactly the same shape
`data_plane.masking.secrets.resolve_hmac_key` already established for
"exactly one place resolves a piece of environment-dependent state."

Local mode only, honestly
--------------------------
There is no real Spark cluster anywhere in this repository's
infrastructure (`infra/` has no `spark-worker`/`spark-master` service --
see `docs/problems/problems_phase_12.md`'s container-build note and
[ADR-0017](../../../../../docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md)).
Every `SparkSession` this module builds uses `local[*]` -- one JVM
process, threads instead of a distributed executor fleet. This is
sufficient to exercise real PySpark *APIs and semantics* (the Catalyst
optimizer, partitioning, broadcast joins, predicate pushdown, the
DataFrame/pandas-UDF execution model) against real data and get real
wall-clock numbers for *this machine*, but it is NOT a substitute for
measuring behavior on an actual multi-node cluster -- shuffle-network
cost, executor-loss recovery, and true horizontal scale-out are
structurally absent from `local[*]`. Every benchmark report this phase
produces says this explicitly rather than implying otherwise (see
`docs/SCALE_AND_PERFORMANCE.md`).

Pinning the worker interpreter (`PYSPARK_PYTHON`)
---------------------------------------------------
Any Python UDF (a plain `@udf`, or a `pandas_udf`) runs inside a
*separate* worker process the JVM launches on demand, communicating with
the driver over a local socket -- not inside this process. If that
worker process resolves a different `python`/`python3` on `PATH` than
the interpreter running this code (a real, reproduced-in-this-repository's-
own-development-environment failure mode on any machine with more than
one Python installation on `PATH`, which is common), the worker crashes
immediately on startup (wrong/missing `pyspark`, wrong pyarrow, ...) --
and because that crash happens before the worker can report a Python
exception back over its own socket, the *driver* only ever sees an
opaque `java.io.IOException: An established connection was aborted`/
`SparkException: Python worker exited unexpectedly (crashed)`, with no
Python traceback at all. `get_local_spark_session` pins both
`PYSPARK_PYTHON` and `PYSPARK_DRIVER_PYTHON` to `sys.executable` (this
exact running interpreter) unless the caller has already set them, which
is the actual fix -- not a workaround -- for this failure mode: it
guarantees the worker is the same interpreter, with the same installed
packages, as the process that built the `SparkSession`.

The Windows `winutils.exe` problem
-----------------------------------
Spark's local file-write path goes through Hadoop's
`RawLocalFileSystem`, which on Windows requires a native shim
(`winutils.exe`/`hadoop.dll`) discoverable via `HADOOP_HOME`. Without it,
every job that *writes* output (reading is unaffected) fails with a
`java.io.FileNotFoundException: HADOOP_HOME and hadoop.home.dir are
unset` error, deep inside the JVM, with no Python-level remediation hint
-- a real, reproduced-in-this-repository's-own-dev-environment problem,
not a hypothetical one. `configure_windows_hadoop_runtime` gives this the
same treatment `data_plane.masking.secrets.resolve_hmac_key` gives a
missing HMAC key: resolve it from a well-known place, or fail loudly with
concrete remediation steps, rather than letting the caller hit an opaque
JVM stack trace. See `scripts/setup_local_spark_windows.py` and this
package's `README.md`.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Iterable
from pathlib import Path

from pyspark.sql import SparkSession

#: Environment variable a caller can set to point at an already-prepared
#: Hadoop-for-Windows runtime directory (one containing `bin/winutils.exe`),
#: overriding auto-detection below. Mirrors
#: `data_plane.masking.secrets.ENV_VAR`'s shape.
HADOOP_RUNTIME_ENV_VAR = "TDM_SPARK_HADOOP_HOME"

#: `local[*]` gives every core on the machine a task slot, which is the
#: honest way to describe "local mode" -- but Spark's SQL engine defaults
#: `spark.sql.shuffle.partitions` to 200 (a sane default for a real
#: multi-node cluster), which on a laptop-sized dataset produces 200
#: mostly-empty output files per shuffle stage -- the "small-file problem"
#: this phase is required to document (see this package's README and
#: `docs/SCALE_AND_PERFORMANCE.md`). A small, explicit default here avoids
#: manufacturing that problem in every benchmark this phase runs; callers
#: benchmarking shuffle behavior itself can override it.
DEFAULT_SHUFFLE_PARTITIONS = 8


class MissingWindowsHadoopRuntimeError(RuntimeError):
    """Raised when running on Windows and no local Hadoop-native-shim
    runtime (`winutils.exe`/`hadoop.dll`) can be found anywhere this
    module knows to look. Carries concrete remediation steps, the same
    way `data_plane.masking.secrets.MissingMaskingKeyError` does for a
    missing HMAC key -- a caller should never have to decode a raw JVM
    stack trace to learn what to do next.
    """


def _default_search_dirs() -> Iterable[Path]:
    """Candidate repository roots to look for `.spark-runtime/` under.

    Mirrors `data_plane.masking.secrets._default_search_dirs`'s exact
    parents-index arithmetic: this file lives at
    `services/data-plane/src/data_plane/spark/session.py`, the same
    depth under the repository root as `masking/secrets.py`.
    """

    here = Path(__file__).resolve()
    service_root = here.parents[3]  # services/data-plane
    repo_root = here.parents[5] if len(here.parents) > 5 else service_root
    seen: set[Path] = set()
    for candidate in (Path.cwd(), service_root, repo_root):
        if candidate not in seen:
            seen.add(candidate)
            yield candidate


def _find_cached_runtime(search_dirs: Iterable[Path]) -> Path | None:
    for directory in search_dirs:
        runtime_root = directory / ".spark-runtime"
        if not runtime_root.is_dir():
            continue
        for child in sorted(runtime_root.glob("hadoop-*")):
            if (child / "bin" / "winutils.exe").is_file():
                return child
    return None


def configure_windows_hadoop_runtime(*, search_dirs: Iterable[Path] | None = None) -> str | None:
    """Resolve and apply the Windows Hadoop-native-shim runtime for this
    process, if applicable.

    Returns the resolved `HADOOP_HOME` directory (as a string) if one was
    found/applied, or `None` on any non-Windows platform (where this is
    simply not needed). Raises `MissingWindowsHadoopRuntimeError` on
    Windows if no runtime can be found anywhere this function knows to
    look. Idempotent -- safe to call once per `get_local_spark_session`
    call, every time.
    """

    if sys.platform != "win32":
        return None

    existing = os.environ.get("HADOOP_HOME")
    if existing:
        return existing

    runtime_dir: Path | None
    override = os.environ.get(HADOOP_RUNTIME_ENV_VAR)
    if override:
        runtime_dir = Path(override)
    else:
        dirs = search_dirs if search_dirs is not None else _default_search_dirs()
        runtime_dir = _find_cached_runtime(dirs)

    if runtime_dir is None or not (runtime_dir / "bin" / "winutils.exe").is_file():
        raise MissingWindowsHadoopRuntimeError(
            "Local-mode PySpark cannot write files on Windows without a "
            "winutils.exe/hadoop.dll native shim, and none was found.\n"
            "To fix this:\n"
            "  1. Run:\n"
            "       python scripts/setup_local_spark_windows.py\n"
            "     (downloads a pinned, community-maintained Hadoop-for-"
            "Windows shim into the git-ignored .spark-runtime/ directory)\n"
            f"  2. Or set {HADOOP_RUNTIME_ENV_VAR}=<path to a directory "
            "containing bin/winutils.exe> yourself.\n"
            "See services/data-plane/src/data_plane/spark/README.md for "
            "why this is needed -- it is a well-known Spark-on-Windows "
            "limitation, not a bug in this repository."
        )

    os.environ["HADOOP_HOME"] = str(runtime_dir)
    bin_dir = str(runtime_dir / "bin")
    current_path = os.environ.get("PATH", "")
    if bin_dir not in current_path.split(os.pathsep):
        os.environ["PATH"] = bin_dir + os.pathsep + current_path
    return str(runtime_dir)


def pin_worker_python_interpreter() -> None:
    """Set `PYSPARK_PYTHON`/`PYSPARK_DRIVER_PYTHON` to `sys.executable`
    unless the caller already set one of them, so the JVM-launched Python
    worker process is guaranteed to be the exact same interpreter (and
    therefore the exact same installed `pyspark`/`pyarrow`/`pandas`) as
    this process. See this module's docstring for the crash this
    prevents. Idempotent and safe to call on every
    `get_local_spark_session` invocation.
    """

    if "PYSPARK_PYTHON" not in os.environ:
        os.environ["PYSPARK_PYTHON"] = sys.executable
    if "PYSPARK_DRIVER_PYTHON" not in os.environ:
        os.environ["PYSPARK_DRIVER_PYTHON"] = sys.executable


def get_local_spark_session(
    app_name: str,
    *,
    shuffle_partitions: int = DEFAULT_SHUFFLE_PARTITIONS,
    extra_conf: dict[str, str] | None = None,
) -> SparkSession:
    """Build (or reuse, via `getOrCreate`) a local-mode `SparkSession`.

    `master("local[*]")` -- see this module's docstring for why: there is
    no real cluster in this repository's infrastructure yet. Sets a small,
    laptop-appropriate `spark.sql.shuffle.partitions` (see
    `DEFAULT_SHUFFLE_PARTITIONS`) and disables the console progress bar
    (noisy under pytest/CI). `extra_conf` lets a caller override or add
    to any of this -- used by `data_plane.benchmarks` to vary shuffle
    partitions for the shuffle-behavior benchmark itself.
    """

    hadoop_home = configure_windows_hadoop_runtime()
    pin_worker_python_interpreter()

    builder = (
        SparkSession.builder.master("local[*]")
        .appName(app_name)
        .config("spark.sql.shuffle.partitions", str(shuffle_partitions))
        .config("spark.sql.adaptive.enabled", "true")
        .config("spark.ui.showConsoleProgress", "false")
        .config("spark.driver.memory", "2g")
    )
    if hadoop_home:
        builder = builder.config("spark.hadoop.hadoop.home.dir", hadoop_home)
    for key, value in (extra_conf or {}).items():
        builder = builder.config(key, value)
    return builder.getOrCreate()


def stop_spark_session(spark: SparkSession) -> None:
    """Stop a session built by `get_local_spark_session`. A thin wrapper
    (not just `spark.stop()`) so call sites read symmetrically and so a
    future phase has one place to add shutdown bookkeeping if needed.
    """

    spark.stop()


__all__ = [
    "DEFAULT_SHUFFLE_PARTITIONS",
    "HADOOP_RUNTIME_ENV_VAR",
    "MissingWindowsHadoopRuntimeError",
    "configure_windows_hadoop_runtime",
    "get_local_spark_session",
    "pin_worker_python_interpreter",
    "stop_spark_session",
]
