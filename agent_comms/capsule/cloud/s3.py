"""
AWS S3 & S3-Compatible Cloud Storage Provider
=============================================
Supports AWS S3, Cloudflare R2, MinIO, Wasabi, and Ceph.
Uses boto3 if installed, with seamless fallback for configuration.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider, CloudCapsuleRecord
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.cloud.s3")


class S3CloudProvider(BaseCloudProvider):
    name = "s3"

    def __init__(
        self,
        bucket: Optional[str] = None,
        region: Optional[str] = None,
        endpoint_url: Optional[str] = None,
        access_key_id: Optional[str] = None,
        secret_access_key: Optional[str] = None,
        prefix: str = "capsules/",
    ):
        self.bucket = bucket or config_manager.get("s3.bucket", "")
        self.region = region or config_manager.get("s3.region", "us-east-1")
        self.endpoint_url = endpoint_url or config_manager.get("s3.endpoint_url", "") or None
        self.access_key_id = access_key_id or config_manager.get("s3.access_key_id", "") or None
        self.secret_access_key = secret_access_key or config_manager.get("s3.secret_access_key", "") or None
        self.prefix = prefix.rstrip("/") + "/"
        self._client = None

    def _get_client(self):
        if self._client is not None:
            return self._client

        try:
            import boto3
        except ImportError:
            raise RuntimeError(
                "boto3 is required for S3 storage. Install via: pip install boto3"
            )

        kwargs: Dict[str, Any] = {"region_name": self.region}
        if self.endpoint_url:
            kwargs["endpoint_url"] = self.endpoint_url
        if self.access_key_id and self.secret_access_key:
            kwargs["aws_access_key_id"] = self.access_key_id
            kwargs["aws_secret_access_key"] = self.secret_access_key

        self._client = boto3.client("s3", **kwargs)
        return self._client

    def _check_bucket(self):
        if not self.bucket:
            raise ValueError(
                "S3 bucket not configured. Set via: agent-comms config set s3.bucket <name> or AWS_S3_BUCKET env var."
            )

    def upload(self, capsule: ContextCapsule) -> str:
        self._check_bucket()
        client = self._get_client()

        key = f"{self.prefix}{capsule.task_id}_{capsule.capsule_id}.json"
        md_key = f"{self.prefix}{capsule.task_id}_{capsule.capsule_id}.md"
        data = capsule.model_dump_json(indent=2).encode("utf-8")
        briefing = capsule.to_briefing_markdown().encode("utf-8")

        client.put_object(
            Bucket=self.bucket,
            Key=key,
            Body=data,
            ContentType="application/json",
            Metadata={
                "task_id": capsule.task_id,
                "capsule_id": capsule.capsule_id,
                "created_at": capsule.created_at,
            },
        )
        # Also upload human-readable markdown briefing
        client.put_object(
            Bucket=self.bucket,
            Key=md_key,
            Body=briefing,
            ContentType="text/markdown",
        )

        uri = f"s3://{self.bucket}/{key}"
        logger.info("Uploaded capsule '%s' to %s", capsule.capsule_id, uri)
        return uri

    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        self._check_bucket()
        client = self._get_client()

        # Extract key if s3:// URI passed
        if capsule_id_or_uri.startswith("s3://"):
            parts = capsule_id_or_uri[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1]
        else:
            bucket = self.bucket
            # Find key matching capsule_id_or_uri
            key = None
            resp = client.list_objects_v2(Bucket=bucket, Prefix=self.prefix)
            for item in resp.get("Contents", []):
                if capsule_id_or_uri in item["Key"] and item["Key"].endswith(".json"):
                    key = item["Key"]
                    break
            if not key:
                raise FileNotFoundError(f"Capsule '{capsule_id_or_uri}' not found in S3 bucket '{bucket}'")

        obj = client.get_object(Bucket=bucket, Key=key)
        raw = obj["Body"].read().decode("utf-8")
        data = json.loads(raw)
        return ContextCapsule.model_validate(data)

    def list_capsules(self) -> List[CloudCapsuleRecord]:
        self._check_bucket()
        client = self._get_client()
        records: List[CloudCapsuleRecord] = []

        paginator = client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=self.prefix):
            for item in page.get("Contents", []):
                key = item["Key"]
                if not key.endswith(".json"):
                    continue
                # Extract filename
                filename = key[len(self.prefix):]
                parts = filename[:-5].split("_", 1)
                task_id = parts[0] if len(parts) > 0 else "unknown"
                capsule_id = parts[1] if len(parts) > 1 else filename[:-5]

                records.append(
                    CloudCapsuleRecord(
                        capsule_id=capsule_id,
                        task_id=task_id,
                        created_at=item["LastModified"].isoformat(),
                        provider="s3",
                        location=f"s3://{self.bucket}/{key}",
                        size_bytes=item.get("Size"),
                    )
                )

        return sorted(records, key=lambda r: r.created_at, reverse=True)

    def delete(self, capsule_id_or_uri: str) -> bool:
        self._check_bucket()
        client = self._get_client()

        if capsule_id_or_uri.startswith("s3://"):
            parts = capsule_id_or_uri[5:].split("/", 1)
            bucket = parts[0]
            key = parts[1]
        else:
            bucket = self.bucket
            key = None
            resp = client.list_objects_v2(Bucket=bucket, Prefix=self.prefix)
            for item in resp.get("Contents", []):
                if capsule_id_or_uri in item["Key"]:
                    key = item["Key"]
                    break
            if not key:
                return False

        client.delete_object(Bucket=bucket, Key=key)
        # Also attempt deleting markdown companion
        md_key = key[:-5] + ".md" if key.endswith(".json") else key + ".md"
        try:
            client.delete_object(Bucket=bucket, Key=md_key)
        except Exception:
            pass
        return True
