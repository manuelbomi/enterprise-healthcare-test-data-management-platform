"""Manual override support.

A human data steward can always override the schema-based or rule-based
classification for a specific `(source_system, dataset, column)` — this is
a required capability per the Phase 2 promptbook and per
DATA_GOVERNANCE.md B.1 ("classification ... always has a ... human-
confirmable status"). Overrides are the highest-precedence input to the
engine (`engine.py`): applied last, always at confidence 1.0, always
recorded with `method=MANUAL_OVERRIDE` and a `confirmed_by` identity so
the resulting classification's `needs_review` is `False`.

Overrides are loaded from a small YAML file
(`manual_overrides.yaml`, next to this module) rather than hardcoded, so
adding one is a config change, not a code change — exactly the kind of
change a data steward (who may not be a Python engineer) should be able
to review in a pull request. See that file for two worked, realistic
examples: one that raises a column's classification (a specialty column
whose *values* include a sensitive category the column-name-only rule
layer cannot see) and one that corrects an automated detector's
context-free guess.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from healthcare_tdm_contracts import SensitivityCategory

DEFAULT_OVERRIDES_PATH = Path(__file__).parent / "manual_overrides.yaml"


@dataclass(frozen=True)
class ManualOverride:
    """One steward-authored override of an automated classification."""

    source_system: str
    dataset: str
    column: str
    category: SensitivityCategory
    reason: str
    confirmed_by: str


def load_overrides(path: Path | None = None) -> dict[tuple[str, str, str], ManualOverride]:
    """Load manual overrides from `path` (default: `manual_overrides.yaml`
    next to this module). Returns a dict keyed by
    `(source_system, dataset, column)` for O(1) lookup by the engine.

    An override file that does not exist is treated as "no overrides"
    (returns `{}`) rather than an error, so the engine works even before
    any steward has authored one.
    """

    resolved = path or DEFAULT_OVERRIDES_PATH
    if not resolved.exists():
        return {}

    raw = yaml.safe_load(resolved.read_text(encoding="utf-8")) or {}
    entries: list[dict[str, Any]] = raw.get("overrides", [])

    overrides: dict[tuple[str, str, str], ManualOverride] = {}
    for entry in entries:
        override = ManualOverride(
            source_system=entry["source_system"],
            dataset=entry["dataset"],
            column=entry["column"],
            category=SensitivityCategory(entry["category"]),
            reason=entry["reason"],
            confirmed_by=entry["confirmed_by"],
        )
        key = (override.source_system, override.dataset, override.column)
        overrides[key] = override
    return overrides


__all__ = ["DEFAULT_OVERRIDES_PATH", "ManualOverride", "load_overrides"]
