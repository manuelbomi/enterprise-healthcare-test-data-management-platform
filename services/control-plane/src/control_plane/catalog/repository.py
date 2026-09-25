"""Catalog repository: reads the JSON catalog artifact the data-plane
discovery engine (`data_plane.discovery.catalog_builder`) produces, and
serves typed `CatalogEntry` query results to the API layer
(`control_plane/api/v1/catalog.py`).

Per ADR-0003 (plane separation) and ADR-0009 (catalog artifact handoff),
this module does not import anything from `data_plane` -- the only shared
code between the two planes is the `CatalogEntry` shape in
`libs/contracts`, which each plane depends on independently.
`data_plane.discovery.catalog_builder.load_catalog` does the same small
amount of JSON-parsing work on the data-plane side (for its own tests and
CLI). Keeping two small, independent copies of "parse this JSON file into
CatalogEntry objects" is the deliberate cost of not having a cross-plane
import — see ADR-0003's "Consequences" section.
"""

from __future__ import annotations

import json
from pathlib import Path

from healthcare_tdm_contracts import CatalogEntry, ClassificationTier, SensitivityCategory


class CatalogNotAvailableError(RuntimeError):
    """Raised when the catalog artifact file does not exist yet.

    This is an expected, recoverable condition (discovery hasn't been run
    yet for this environment) -- the API layer turns it into an HTTP 503,
    not a 500, so a client can distinguish "not configured yet" from "the
    service is broken."
    """


class CatalogRepository:
    """Read-only access to one catalog JSON artifact.

    Loads and caches the artifact on first use; call `reload()` to force
    a re-read (e.g., after a new discovery run) without restarting the
    process.
    """

    def __init__(self, path: Path) -> None:
        self._path = path
        self._entries: list[CatalogEntry] | None = None

    @property
    def path(self) -> Path:
        return self._path

    def reload(self) -> None:
        self._entries = None

    def _ensure_loaded(self) -> list[CatalogEntry]:
        if self._entries is None:
            if not self._path.exists():
                raise CatalogNotAvailableError(
                    f"Catalog artifact not found at '{self._path}'. Generate one with "
                    "'python -m data_plane.reference_data.cli --scale tiny --out-dir "
                    "<estate-dir>' followed by 'python -m data_plane.discovery.cli "
                    "--estate-dir <estate-dir>' (see docs/adr/0009-catalog-artifact-"
                    "handoff.md), then point TDM_CONTROL_PLANE_CATALOG_PATH at the "
                    "resulting catalog.json."
                )
            raw = json.loads(self._path.read_text(encoding="utf-8"))
            self._entries = [CatalogEntry.model_validate(row) for row in raw]
        return self._entries

    def list_entries(
        self,
        *,
        source_system: str | None = None,
        dataset: str | None = None,
        category: SensitivityCategory | None = None,
        tier: ClassificationTier | None = None,
        needs_review: bool | None = None,
    ) -> list[CatalogEntry]:
        """Every entry matching all given filters (AND semantics); `None`
        means "don't filter on this field."."""

        results: list[CatalogEntry] = []
        for entry in self._ensure_loaded():
            if source_system is not None and entry.source != source_system:
                continue
            if dataset is not None and entry.dataset != dataset:
                continue
            if category is not None and entry.classification.category != category:
                continue
            if tier is not None and entry.classification.tier != tier:
                continue
            if needs_review is not None and entry.classification.needs_review != needs_review:
                continue
            results.append(entry)
        return results

    def get_entry(self, source_system: str, dataset: str, column: str) -> CatalogEntry | None:
        for entry in self._ensure_loaded():
            if entry.source == source_system and entry.dataset == dataset and entry.column == column:
                return entry
        return None

    def list_datasets(self) -> list[dict[str, object]]:
        """One row per `(source_system, dataset)`: column count, the most
        severe category present (per `SensitivityCategory.precedence()`),
        and the dataset's owner -- a dataset-level overview for a steward
        who wants "what datasets exist and how sensitive are they," not a
        column-by-column dump."""

        by_key: dict[tuple[str, str], list[CatalogEntry]] = {}
        for entry in self._ensure_loaded():
            by_key.setdefault((entry.source, entry.dataset), []).append(entry)

        precedence = {category: i for i, category in enumerate(SensitivityCategory.precedence())}
        rows: list[dict[str, object]] = []
        for (source_system, dataset), items in sorted(by_key.items()):
            most_severe = min(
                items,
                key=lambda e: precedence[e.classification.category or SensitivityCategory.SENSITIVE],
            )
            rows.append(
                {
                    "source_system": source_system,
                    "dataset": dataset,
                    "column_count": len(items),
                    "most_severe_category": most_severe.classification.category,
                    "owner": items[0].owner,
                }
            )
        return rows

    def summary(self) -> dict[str, object]:
        """Aggregate catalog-wide counts: total columns/datasets, a
        breakdown by category, and how many entries still need steward
        review (see `ColumnClassification.needs_review`)."""

        entries = self._ensure_loaded()
        by_category: dict[str, int] = {}
        for entry in entries:
            key = entry.classification.category.value if entry.classification.category else "unknown"
            by_category[key] = by_category.get(key, 0) + 1
        return {
            "total_columns": len(entries),
            "total_datasets": len({(e.source, e.dataset) for e in entries}),
            "by_category": by_category,
            "needs_review": sum(1 for e in entries if e.classification.needs_review),
        }


__all__ = ["CatalogNotAvailableError", "CatalogRepository"]
