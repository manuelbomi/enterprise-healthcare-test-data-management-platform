#!/usr/bin/env python
"""One-time, explicit, opt-in setup for running local-mode PySpark on a
Windows development machine (Phase 14).

Why this exists
----------------
PySpark's local file-write path (used by every `DataFrameWriter.parquet`/
`.csv` call, and internally by shuffle/temp-dir bookkeeping) goes through
Hadoop's `RawLocalFileSystem`, which on Windows needs a small native shim
-- `winutils.exe` and `hadoop.dll` -- to exist under a directory pointed
to by the `HADOOP_HOME` environment variable. Without it, every Spark job
that writes output (not just reads) fails with:

    java.io.FileNotFoundException: HADOOP_HOME and hadoop.home.dir are
    unset. -see https://cwiki.apache.org/confluence/display/HADOOP2/WindowsProblems

This is a well-known, long-standing Spark-on-Windows limitation, not a
bug in this repository's code -- see
`services/data-plane/src/data_plane/spark/README.md` and
[ADR-0017](../docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md)
for the full account.

This script downloads a matching `winutils.exe`/`hadoop.dll` pair (a
widely used, community-maintained build for Hadoop 3.3.6 -- close enough
to the Hadoop client jars PySpark 4.x bundles that the native shim works
correctly for local-filesystem operations, which is all it is used for)
from a pinned URL, into a git-ignored local cache directory
(`<repo_root>/.spark-runtime/hadoop-3.3.6/bin/`). It never writes outside
that directory, never modifies system-wide environment variables (that
is `data_plane.spark.session.get_local_spark_session`'s job, done
per-process, every time a session is built -- see that module), and does
nothing at all on non-Windows platforms (they do not need this shim).

This script makes a network call ONLY when explicitly run by a human --
nothing in `data_plane` imports or calls it automatically.

Usage::

    python scripts/setup_local_spark_windows.py
    python scripts/setup_local_spark_windows.py --force   # re-download even if already cached
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
HADOOP_VERSION = "3.3.6"
CACHE_ROOT = REPO_ROOT / ".spark-runtime" / f"hadoop-{HADOOP_VERSION}" / "bin"
BASE_URL = f"https://raw.githubusercontent.com/cdarlint/winutils/master/hadoop-{HADOOP_VERSION}/bin"
FILES = ("winutils.exe", "hadoop.dll")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--force", action="store_true", help="Re-download even if already cached locally."
    )
    args = parser.parse_args(argv)

    if sys.platform != "win32":
        print(
            "This script is a no-op on non-Windows platforms -- local-mode "
            "PySpark file writes do not need a winutils.exe shim on "
            "Linux/macOS. Nothing was downloaded."
        )
        return 0

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    for filename in FILES:
        dest = CACHE_ROOT / filename
        if dest.exists() and not args.force:
            print(f"Already cached: {dest} (sha256={_sha256(dest)})")
            continue
        url = f"{BASE_URL}/{filename}"
        print(f"Downloading {url} -> {dest}")
        urllib.request.urlretrieve(url, dest)  # noqa: S310 -- pinned https URL, operator-run only
        print(f"  wrote {dest} ({dest.stat().st_size} bytes, sha256={_sha256(dest)})")

    print()
    print(f"HADOOP_HOME candidate ready at: {CACHE_ROOT.parent}")
    print(
        "You do not need to set HADOOP_HOME yourself -- "
        "data_plane.spark.session.get_local_spark_session() auto-detects "
        f"'{CACHE_ROOT.parent.relative_to(REPO_ROOT)}' under the repository "
        "root on every call. Set the TDM_SPARK_HADOOP_HOME environment "
        "variable instead if you want to point at a different runtime."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
