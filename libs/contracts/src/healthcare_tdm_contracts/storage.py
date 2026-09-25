"""Object storage adapter interface.

See docs/adr/0005-object-storage-abstraction.md for the reasoning. This
module defines the interface every concrete backend (MinIO, AWS S3, Azure
Blob/ADLS, and any future open-source healthcare data repository adapter)
must implement. No concrete implementation lives in this package — this
is a contract, not an adapter.
"""

from __future__ import annotations

from enum import Enum
from typing import Protocol

from pydantic import BaseModel, Field


class StorageBackend(str, Enum):
    """Which concrete storage adapter is active.

    Selected via configuration/environment, never branched on inside
    job logic — see ADR-0005.
    """

    MINIO = "minio"
    AWS_S3 = "aws_s3"
    AZURE_BLOB = "azure_blob"


class ObjectRef(BaseModel):
    """A fully-qualified reference to an object in storage.

    This is the shape passed between planes when referring to data at
    rest (e.g., a JobResult.output_ref or a SnapshotRecord.storage_ref
    resolve through this shape) rather than a bare string path, so the
    backend and bucket/container are always explicit.
    """

    backend: StorageBackend
    bucket: str = Field(..., description="Bucket (S3/MinIO) or container (Azure) name.")
    key: str = Field(..., description="Object key/path within the bucket or container.")


class ObjectStorageAdapter(Protocol):
    """The interface every storage backend adapter must implement.

    Implementations live in the data-plane and control-plane packages
    (Phase 5), not here — this Protocol exists so job code can be written
    and type-checked against the interface without depending on any
    concrete backend's SDK.
    """

    def get_object(self, ref: ObjectRef) -> bytes:
        """Fetch an object's bytes. Raises if the object does not exist."""
        ...

    def put_object(self, ref: ObjectRef, data: bytes) -> None:
        """Write an object's bytes, creating or overwriting it."""
        ...

    def list_objects(self, backend: StorageBackend, bucket: str, prefix: str) -> list[ObjectRef]:
        """List objects under a prefix."""
        ...

    def delete_object(self, ref: ObjectRef) -> None:
        """Delete an object. Must be idempotent (deleting a missing object is not an error)."""
        ...

    def generate_presigned_url(self, ref: ObjectRef, expires_in_seconds: int) -> str:
        """Generate a time-limited URL for direct (out-of-band) access to an object."""
        ...
