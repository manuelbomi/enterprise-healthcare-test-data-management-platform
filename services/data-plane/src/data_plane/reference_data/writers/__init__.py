"""Per-source-system writers.

Each module here persists the in-memory :class:`~data_plane.reference_data
.generator.GeneratedEstate` into the on-disk shape that would, in a real
deployment, live in that source system's actual storage technology (a
relational database, an object-storage bucket, an ADLS container, or a
partner file drop). Locally, "the bucket"/"the container" is simulated as
a directory tree under the generator's output root using the same
bucket/key naming a real deployment would use against MinIO/S3/ADLS (see
``docs/adr/0005-object-storage-abstraction.md`` — real adapter
implementations land in Phase 5; these writers only need to produce
byte-identical *content*, not talk to a live object store, to satisfy
this phase's scope).
"""

from __future__ import annotations
