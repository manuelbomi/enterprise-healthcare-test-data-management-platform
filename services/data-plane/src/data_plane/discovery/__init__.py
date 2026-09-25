"""PHI/PII discovery & classification (Phase 2).

Scans a source dataset's schema and (synthetic-only) sample data to
produce `ColumnClassification`/`CatalogEntry` records (see
`libs/contracts/src/healthcare_tdm_contracts/classification.py` and
`catalog.py`) using three layers, in precedence order:

1. **Schema-based** (`schema_rules.py`) — an explicit, human-authored
   table covering every field of all 14 Phase 1 entities
   (`data_plane.reference_data.domain`).
2. **Rule-based** (`pattern_rules.py`) — column-name (and optionally
   sample-value) pattern detectors, consulted only for columns the schema
   layer doesn't recognize (schema drift, partner-specific abbreviations,
   genuinely unknown columns).
3. **Manual override** (`overrides.py`) — a human data steward's decision,
   always highest precedence.

`engine.py`'s `ClassificationEngine` combines all three and applies
DATA_GOVERNANCE.md B.1's conservative-default rule when nothing matches.
`scanner.py` reads the actual generated Phase 1 estate (SQLite, Parquet,
NDJSON, CSV, partner flat-file/JSON) to enumerate real columns.
`catalog_builder.py` turns classified columns into the full data catalog
(`CatalogEntry`: classification + masking requirement + owner + retention
classification) and writes/reads it as a JSON artifact. `cli.py` is the
command-line entry point.

See `README.md` in this directory for how to run it, and
`docs/PHI_PII_CLASSIFICATION_LIMITATIONS.md` for what this engine can and
cannot prove — regex/schema-based classification is a triage tool, not a
HIPAA-compliance guarantee.
"""

from data_plane.discovery.catalog_builder import build_catalog, load_catalog, write_catalog
from data_plane.discovery.engine import ClassificationEngine, ColumnToClassify

__all__ = [
    "ClassificationEngine",
    "ColumnToClassify",
    "build_catalog",
    "load_catalog",
    "write_catalog",
]
