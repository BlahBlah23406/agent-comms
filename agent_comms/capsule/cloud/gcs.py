"""
Google Cloud Storage (GCS) Provider
===================================
Supports saving and retrieving Context Capsules from GCS buckets.
Uses google-cloud-storage if installed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider, CloudCapsuleRecord
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.cloud.gcs")


class GCSCloudProvider(BaseCloudProvider):
    name = "gcs"

    def __init__(
        self,
        bucket: Optional[str] = None,
        project: Optional[str] = None,
        credentials_file: Optional[str] = None,
        prefix: str = "capsules/",
    ):
        self.bucket_name = bucket or config_manager.get("gcs.bucket", "")
        self.project = project or config_manager.get("gcs.project", "") or None
        self.credentials_file = credentials_file or config_manager.get("gcs.credentials_file", "") or None
        self.prefix = prefix.rstrip("/") + "/"
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            from google.cloud import storage
        except ImportError:
            raise RuntimeError(
                "google-cloud-storage is required for GCS. Install via: pip install google-cloud-storage"
            )

        if self.credentials_file:
            self._client = storage.Client.from_service_account_json(
                self.credentials_file, project=self.project
            )
        else:
            self._client = storage.Client(project=self.project)
        return self._client

    def _check_bucket(self):
        if not self.bucket_name:
            raise ValueError(
                "GCS bucket not configured. Set via: agent-comms config set gcs.bucket <name> or GCS_BUCKET env var."
            )

    def upload(self, capsule: ContextCapsule) -> str:
        self._check_bucket()
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)

        blob_name = f"{self.prefix}{capsule.task_id}_{capsule.capsule_id}.json"
        md_name = f"{self.prefix}{capsule.task_id}_{capsule.capsule_id}.md"

        blob = bucket.blob(blob_name)
        blob.upload_from_string(
            capsule.model_dump_json(indent=2),
            content_type="application/json",
        )

        md_blob = bucket.blob(md_name)
        md_blob.upload_from_string(
            capsule.to_briefing_markdown(),
            content_type="text/markdown",
        )

        uri = f"gs://{self.bucket_name}/{blob_name}"
        logger.info("Uploaded capsule '%s' to %s", capsule.capsule_id, uri)
        return uri

    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        self._check_bucket()
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)

        if capsule_id_or_uri.startswith("gs://"):
            parts = capsule_id_or_uri[5:].split("/", 1)
            blob_name = parts[1]
            blob = client.bucket(parts[0]).blob(blob_name)
        else:
            blob = None
            blobs = list(bucket.list_blobs(prefix=self.prefix))
            for b in blobs:
                if capsule_id_or_uri in b.name and b.name.endswith(".json"):
                    blob = b
                    break
            if not blob:
                raise FileNotFoundError(f"Capsule '{capsule_id_or_uri}' not found in GCS bucket '{self.bucket_name}'")

        raw = blob.download_as_text()
        return ContextCapsule.model_validate(json.loads(raw))

    def list_capsules(self) -> List[CloudCapsuleRecord]:
        self._check_bucket()
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)
        records: List[CloudCapsuleRecord] = []

        for b in bucket.list_blobs(prefix=self.prefix):
            if not b.name.endswith(".json"):
                continue
            filename = b.name[len(self.prefix):]
            parts = filename[:-5].split("_", 1)
            task_id = parts[0] if len(parts) > 0 else "unknown"
            capsule_id = parts[1] if len(parts) > 1 else filename[:-5]

            records.append(
                CloudCapsuleRecord(
                    capsule_id=capsule_id,
                    task_id=task_id,
                    created_at=b.time_created.isoformat() if b.time_created else "",
                    provider="gcs",
                    location=f"gs://{self.bucket_name}/{b.name}",
                    size_bytes=b.size,
                )
            )

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def delete(self, capsule_id_or_uri: str) -> bool:
        self._check_bucket()
        client = self._get_client()
        bucket = client.bucket(self.bucket_name)

        if capsule_id_or_uri.startswith("gs://"):
            parts = capsule_id_or_uri[5:].split("/", 1)
            blob = client.bucket(parts[0]).blob(parts[1])
        else:
            blob = None
            for b in bucket.list_blobs(prefix=self.prefix):
                if capsule_id_or_uri in b.name:
                    blob = b
                    break
            if not blob:
                return False

        blob.delete()
        return True
