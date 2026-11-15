"""Optional Google Cloud Storage archival/cache client for FITS cutouts, NPZ cubes, and PNGs."""

from __future__ import annotations

from dataclasses import dataclass
import functools
import hashlib
import logging
import os
from pathlib import Path
from typing import Any

DEFAULT_GCS_PROJECT = "nebo-514718"
DEFAULT_GCS_BUCKET = "nebo-514718-spherex-assets"
DEFAULT_GCS_PREFIX = "nebo-spherex"

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class StoredObjectRef:
    bucket: str
    object_name: str
    gcs_uri: str
    sha256_hex: str
    byte_size: int
    content_type: str
    crc32c: str | None = None


def _import_gcs_storage() -> Any:
    try:
        from google.cloud import storage  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover - optional runtime dependency
        raise RuntimeError(
            "google-cloud-storage is not installed; set NEBO_GCS_BUCKET empty or install it."
        ) from exc
    return storage


@functools.lru_cache(maxsize=4)
def _shared_client(bucket_name: str, project: str | None, prefix: str) -> "GCSStorageClient":
    # One storage.Client per config: building it per call costs auth and setup every time.
    return GCSStorageClient(bucket_name=bucket_name, project=project, prefix=prefix)


class GCSStorageClient:
    """Thin wrapper over google.cloud.storage configured via env vars."""

    def __init__(
        self,
        bucket_name: str = DEFAULT_GCS_BUCKET,
        project: str | None = DEFAULT_GCS_PROJECT,
        prefix: str = DEFAULT_GCS_PREFIX,
        client: Any = None,
    ) -> None:
        self.bucket_name = bucket_name
        self.project = project
        self.prefix = prefix.strip("/")
        self._client = client

    @classmethod
    def from_env(cls) -> "GCSStorageClient | None":
        bucket_name = os.environ.get("NEBO_GCS_BUCKET", "").strip()
        if not bucket_name:
            return None
        project = os.environ.get("NEBO_GCS_PROJECT", DEFAULT_GCS_PROJECT).strip() or None
        prefix = os.environ.get("NEBO_GCS_PREFIX", DEFAULT_GCS_PREFIX).strip() or DEFAULT_GCS_PREFIX
        return _shared_client(bucket_name, project, prefix)

    def _get_bucket(self) -> Any:
        if self._client is None:
            storage = _import_gcs_storage()
            self._client = storage.Client(project=self.project)
        return self._client.bucket(self.bucket_name)

    def build_object_name(self, *parts: str) -> str:
        clean_parts = [str(p).strip("/") for p in parts if str(p).strip("/")]
        if self.prefix:
            return "/".join([self.prefix, *clean_parts])
        return "/".join(clean_parts)

    def build_gcs_uri(self, object_name: str) -> str:
        return f"gs://{self.bucket_name}/{object_name.lstrip('/')}"

    def upload_bytes(
        self,
        object_name: str,
        payload: bytes,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectRef:
        clean_name = object_name.lstrip("/")
        sha256_hex = hashlib.sha256(payload).hexdigest()
        bucket = self._get_bucket()
        blob = bucket.blob(clean_name)
        blob.upload_from_string(payload, content_type=content_type)
        crc32c = getattr(blob, "crc32c", None)
        return StoredObjectRef(
            bucket=self.bucket_name,
            object_name=clean_name,
            gcs_uri=self.build_gcs_uri(clean_name),
            sha256_hex=sha256_hex,
            byte_size=len(payload),
            content_type=content_type,
            crc32c=crc32c,
        )

    def upload_file(
        self,
        local_path: Path,
        object_name: str,
        content_type: str = "application/octet-stream",
    ) -> StoredObjectRef:
        payload = local_path.read_bytes()
        return self.upload_bytes(object_name, payload, content_type=content_type)

    def download_bytes(self, object_name: str) -> bytes | None:
        clean_name = object_name.lstrip("/")
        bucket = self._get_bucket()
        blob = bucket.blob(clean_name)
        if not blob.exists():
            return None
        return bytes(blob.download_as_bytes())

    def download_file(self, object_name: str, local_path: Path) -> bool:
        data = self.download_bytes(object_name)
        if data is None:
            return False
        local_path.parent.mkdir(parents=True, exist_ok=True)
        local_path.write_bytes(data)
        return True
