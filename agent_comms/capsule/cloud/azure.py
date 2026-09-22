"""
Azure Blob Storage Provider
===========================
Supports saving and retrieving Context Capsules from Azure Blob Storage containers.
Uses azure-storage-blob if installed.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider, CloudCapsuleRecord
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.cloud.azure")


class AzureBlobCloudProvider(BaseCloudProvider):
    name = "azure"

    def __init__(
        self,
        connection_string: Optional[str] = None,
        container_name: Optional[str] = None,
        prefix: str = "capsules/",
    ):
        self.connection_string = connection_string or config_manager.get("azure.connection_string", "")
        self.container_name = container_name or config_manager.get("azure.container_name", "capsules")
        self.prefix = prefix.rstrip("/") + "/"
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            from azure.storage.blob import BlobServiceClient
        except ImportError:
            raise RuntimeError(
                "azure-storage-blob is required for Azure storage. Install via: pip install azure-storage-blob"
            )

        if not self.connection_string:
            raise ValueError(
                "Azure connection string not configured. Set via: agent-comms config set azure.connection_string <conn_str> or AZURE_STORAGE_CONNECTION_STRING env var."
            )

        self._client = BlobServiceClient.from_connection_string(self.connection_string)
        return self._client

    def upload(self, capsule: ContextCapsule) -> str:
        service_client = self._get_client()
        container_client = service_client.get_container_client(self.container_name)
        if not container_client.exists():
            container_client.create_container()

        blob_name = f"{self.prefix}{capsule.task_id}_{capsule.capsule_id}.json"
        md_name = f"{self.prefix}{capsule.task_id}_{capsule.capsule_id}.md"

        container_client.upload_blob(
            name=blob_name,
            data=capsule.model_dump_json(indent=2).encode("utf-8"),
            overwrite=True,
        )
        container_client.upload_blob(
            name=md_name,
            data=capsule.to_briefing_markdown().encode("utf-8"),
            overwrite=True,
        )

        uri = f"azure://{self.container_name}/{blob_name}"
        logger.info("Uploaded capsule '%s' to %s", capsule.capsule_id, uri)
        return uri

    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        service_client = self._get_client()
        container_client = service_client.get_container_client(self.container_name)

        if capsule_id_or_uri.startswith("azure://"):
            parts = capsule_id_or_uri[8:].split("/", 1)
            blob_name = parts[1]
        else:
            blob_name = None
            blobs = container_client.list_blobs(name_starts_with=self.prefix)
            for b in blobs:
                if capsule_id_or_uri in b.name and b.name.endswith(".json"):
                    blob_name = b.name
                    break
            if not blob_name:
                raise FileNotFoundError(f"Capsule '{capsule_id_or_uri}' not found in Azure container '{self.container_name}'")

        blob_client = container_client.get_blob_client(blob_name)
        raw = blob_client.download_blob().readall().decode("utf-8")
        return ContextCapsule.model_validate(json.loads(raw))

    def list_capsules(self) -> List[CloudCapsuleRecord]:
        service_client = self._get_client()
        container_client = service_client.get_container_client(self.container_name)
        if not container_client.exists():
            return []

        records: List[CloudCapsuleRecord] = []
        for b in container_client.list_blobs(name_starts_with=self.prefix):
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
                    created_at=b.last_modified.isoformat() if b.last_modified else "",
                    provider="azure",
                    location=f"azure://{self.container_name}/{b.name}",
                    size_bytes=b.size,
                )
            )

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def delete(self, capsule_id_or_uri: str) -> bool:
        service_client = self._get_client()
        container_client = service_client.get_container_client(self.container_name)
        if not container_client.exists():
            return False

        if capsule_id_or_uri.startswith("azure://"):
            parts = capsule_id_or_uri[8:].split("/", 1)
            blob_name = parts[1]
        else:
            blob_name = None
            for b in container_client.list_blobs(name_starts_with=self.prefix):
                if capsule_id_or_uri in b.name:
                    blob_name = b.name
                    break
            if not blob_name:
                return False

        container_client.delete_blob(blob_name)
        return True
