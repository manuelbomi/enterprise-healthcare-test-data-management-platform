"""Real PySpark implementations of the two data-plane operations Phase 14
identifies as most plausibly benefiting from horizontal scaling (see
`ROADMAP.md` Phase 14 and
`docs/adr/0017-pyspark-benchmark-tooling-in-data-plane.md`).

Module map
----------
- `session.py` -- the one place a `SparkSession` is constructed
  (`get_local_spark_session`), including the Windows
  `winutils.exe`/`HADOOP_HOME` workaround every local-mode write needs
  on this platform.
- `masking_job.py` -- masks the claims-warehouse `claim` table's direct
  identifiers with a `pandas_udf` that reuses Phase 3's real
  `MaskingEngine` (`run_claims_masking_job`). No shuffle: every row's
  masked value depends only on that row.
- `subsetting_job.py` -- selects a random N% of members and pulls their
  full claim/claim-line closure via two broadcast joins
  (`run_member_subsetting_job`). No shuffle of the large tables: only
  the small "which members/claim ids are selected" side is broadcast.

Neither module writes to Delta tables -- see this package's `README.md`
for why (no cached Delta Lake Maven artifacts could be assumed present in
every environment this repository is reviewed in) and for the honest
account of what is documented-but-not-executed (Delta optimization
concepts, autoscaling) versus what actually runs (everything else this
package exports).

Like every other data-plane engine (`data_plane.discovery`,
`data_plane.masking`, `data_plane.capacity`, ...), this package never
imports `control_plane` -- it operates only on filesystem paths and the
`healthcare_tdm_contracts`/sibling `data_plane` shapes it already
depends on.
"""

from data_plane.spark.masking_job import (
    DEFAULT_MASKED_COLUMNS,
    SparkMaskingResult,
    run_claims_masking_job,
)
from data_plane.spark.session import (
    MissingWindowsHadoopRuntimeError,
    get_local_spark_session,
    stop_spark_session,
)
from data_plane.spark.subsetting_job import SparkSubsettingResult, run_member_subsetting_job

__all__ = [
    "DEFAULT_MASKED_COLUMNS",
    "MissingWindowsHadoopRuntimeError",
    "SparkMaskingResult",
    "SparkSubsettingResult",
    "get_local_spark_session",
    "run_claims_masking_job",
    "run_member_subsetting_job",
    "stop_spark_session",
]
