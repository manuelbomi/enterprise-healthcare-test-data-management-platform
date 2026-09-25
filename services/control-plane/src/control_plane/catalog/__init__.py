"""Data catalog: control-plane read access to the PHI/PII classification
catalog the data-plane discovery engine produces.

Per ADR-0003 (plane separation), the control plane never imports
`data_plane` internals. Per ADR-0009 (`docs/adr/0009-catalog-artifact-
handoff.md`), the catalog is currently handed between planes as a JSON
file (`CatalogEntry` rows, the shared `libs/contracts` shape) rather than
a database row -- the real metadata-plane PostgreSQL schema
(`docs/adr/0004-postgresql-metadata-store.md`) doesn't exist yet. This
package's `repository.CatalogRepository` reads that artifact and answers
the queries `api/v1/catalog.py` exposes.
"""

from control_plane.catalog.repository import CatalogNotAvailableError, CatalogRepository

__all__ = ["CatalogNotAvailableError", "CatalogRepository"]
