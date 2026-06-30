"""
Subida opcional de imágenes a Google Cloud Storage o guardado local.

En Docker el backend por defecto es local, usando un volumen persistente.
"""

import hashlib
import logging
import mimetypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional
from urllib.parse import urlparse

import requests

from dtc.config.settings import config

logger = logging.getLogger(__name__)


@dataclass
class StoredImage:
    source_url: str
    storage_url: Optional[str]
    storage_path: Optional[str]
    content_type: Optional[str]
    checksum: Optional[str]


class GCSImageStorage:
    """Cliente pequeño para guardar imágenes remotas en GCS o disco local."""

    def __init__(self):
        self.backend = config.storage.backend
        self.enabled = config.storage.enabled or self.backend == "local"
        self.bucket_name = config.storage.bucket
        self.prefix = config.storage.prefix.strip("/")
        self.public_base_url = config.storage.public_base_url
        self.local_dir = config.storage.local_dir
        self.local_public_base_url = config.storage.local_public_base_url.rstrip("/")
        self._bucket = None

        if self.backend == "gcs" and self.enabled:
            if not self.bucket_name:
                raise ValueError("DTC_GCS_BUCKET es requerido cuando Storage está activo.")
            from google.cloud import storage

            client = storage.Client()
            self._bucket = client.bucket(self.bucket_name)

    def store_listing_image(
        self,
        source_name: str,
        external_id: str,
        capture_date: str,
        image_url: str,
        image_order: int,
    ) -> StoredImage:
        if not self.enabled or self.backend == "passthrough":
            return StoredImage(
                source_url=image_url,
                storage_url=image_url,
                storage_path=None,
                content_type=None,
                checksum=None,
            )

        response = requests.get(image_url, timeout=30)
        response.raise_for_status()
        payload = response.content
        checksum = hashlib.sha256(payload).hexdigest()
        content_type = response.headers.get("content-type") or self._guess_content_type(image_url)
        extension = self._guess_extension(image_url, content_type)
        path = (
            f"{self.prefix}/{source_name.lower()}/{capture_date}/"
            f"{external_id}/{image_order:02d}-{checksum[:16]}{extension}"
        )

        if self.backend == "local":
            return self._store_local(image_url, payload, path, content_type, checksum)

        blob = self._bucket.blob(path)
        if not blob.exists():
            blob.upload_from_string(payload, content_type=content_type)
            logger.info("Imagen subida a GCS: gs://%s/%s", self.bucket_name, path)

        storage_url = self._public_url(path)
        return StoredImage(
            source_url=image_url,
            storage_url=storage_url,
            storage_path=path,
            content_type=content_type,
            checksum=checksum,
        )

    def _store_local(
        self,
        image_url: str,
        payload: bytes,
        path: str,
        content_type: Optional[str],
        checksum: str,
    ) -> StoredImage:
        target = self.local_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        if not target.exists():
            target.write_bytes(payload)
            logger.info("Imagen guardada localmente: %s", target)
        return StoredImage(
            source_url=image_url,
            storage_url=f"{self.local_public_base_url}/{path}",
            storage_path=str(target),
            content_type=content_type,
            checksum=checksum,
        )

    def _public_url(self, path: str) -> str:
        if self.public_base_url:
            return f"{self.public_base_url.rstrip('/')}/{path}"
        return f"https://storage.googleapis.com/{self.bucket_name}/{path}"

    @staticmethod
    def _guess_content_type(url: str) -> str:
        guessed, _ = mimetypes.guess_type(urlparse(url).path)
        return guessed or "application/octet-stream"

    @staticmethod
    def _guess_extension(url: str, content_type: Optional[str]) -> str:
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix in {".jpg", ".jpeg", ".png", ".webp"}:
            return suffix
        guessed = mimetypes.guess_extension(content_type or "")
        return guessed if guessed in {".jpg", ".jpeg", ".png", ".webp"} else ".jpg"
