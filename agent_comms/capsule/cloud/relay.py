"""
Unified Storage & Relay Hub Cloud Storage Provider
==================================================
Stores, lists, and retrieves Context Capsules directly via the Unified Storage
Server or AHRP Relay REST API over local network or Tailscale.
Zero extra dependencies required (uses Python standard library urllib).
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider, CloudCapsuleRecord
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.cloud.relay")


class RelayCloudProvider(BaseCloudProvider):
    name = "relay"

    def __init__(self, relay_url: Optional[str] = None, storage_url: Optional[str] = None):
        target_url = (
            storage_url
            or relay_url
            or os.environ.get("AGENT_COMMS_STORAGE_URL")
            or config_manager.get("storage_server_url")
            or os.environ.get("AGENT_COMMS_RELAY")
            or config_manager.get("default_relay_url")
            or "http://localhost:8765"
        )

        raw_url = str(target_url).strip()
        # Convert ws/wss to http/https for REST endpoints
        if raw_url.startswith("ws://"):
            raw_url = "http://" + raw_url[5:]
        elif raw_url.startswith("wss://"):
            raw_url = "https://" + raw_url[6:]
        elif not raw_url.startswith("http://") and not raw_url.startswith("https://"):
            raw_url = f"http://{raw_url}"

        # Remove trailing /ws
        if raw_url.endswith("/ws"):
            raw_url = raw_url[:-3]
        self.base_url = raw_url.rstrip("/")

    def upload(self, capsule: ContextCapsule) -> str:
        url = f"{self.base_url}/capsules"
        data = capsule.model_dump_json().encode("utf-8")
        req = urllib.request.Request(
            url,
            data=data,
            headers={"Content-Type": "application/json", "User-Agent": "agent-comms/1.1"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                cid = result.get("capsule_id", capsule.capsule_id)
                scheme = self.name if self.name in ("relay", "storage") else "storage"
                uri = f"{scheme}://{self.base_url}/capsules/{cid}"
                logger.info("Uploaded capsule '%s' to %s: %s", cid, self.name, uri)
                return uri
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to upload capsule to {self.name} ({self.base_url}): {e}")

    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        cid = capsule_id_or_uri
        if "://" in cid:
            cid = cid.split("/")[-1]

        url = f"{self.base_url}/capsules/{cid}"
        req = urllib.request.Request(url, headers={"User-Agent": "agent-comms/1.1"}, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return ContextCapsule.model_validate(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(f"Capsule '{cid}' not found on storage server at {self.base_url}")
            raise RuntimeError(f"Storage server error ({e.code}): {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not connect to storage server at {self.base_url}: {e}")

    def download_briefing(self, capsule_id_or_uri: str) -> str:
        """Retrieves companion Markdown briefing for a capsule."""
        cid = capsule_id_or_uri
        if "://" in cid:
            cid = cid.split("/")[-1]

        url = f"{self.base_url}/capsules/{cid}/briefing"
        req = urllib.request.Request(url, headers={"User-Agent": "agent-comms/1.1"}, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.read().decode("utf-8")
        except Exception:
            cap = self.download(cid)
            return cap.to_briefing_markdown()

    def list_capsules(self, query: Optional[str] = None, task_id: Optional[str] = None) -> List[CloudCapsuleRecord]:
        params = {}
        if query:
            params["q"] = query
        if task_id:
            params["task_id"] = task_id

        query_str = f"?{urllib.parse.urlencode(params)}" if params else ""
        url = f"{self.base_url}/capsules{query_str}"
        req = urllib.request.Request(url, headers={"User-Agent": "agent-comms/1.1"}, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                items = json.loads(resp.read().decode("utf-8"))
                records = []
                for item in items:
                    cid = item.get("capsule_id", "unknown")
                    records.append(
                        CloudCapsuleRecord(
                            capsule_id=cid,
                            task_id=item.get("task_id", "unknown"),
                            created_at=item.get("created_at", ""),
                            title=item.get("title"),
                            summary=item.get("executive_summary", ""),
                            provider=self.name,
                            location=f"{self.name}://{self.base_url}/capsules/{cid}",
                            size_bytes=item.get("size_bytes"),
                        )
                    )
                return records
        except Exception as e:
            logger.debug(f"Could not query storage capsules at {self.base_url}: {e}")
            return []

    def delete(self, capsule_id_or_uri: str) -> bool:
        cid = capsule_id_or_uri
        if "://" in cid:
            cid = cid.split("/")[-1]

        url = f"{self.base_url}/capsules/{cid}"
        req = urllib.request.Request(url, headers={"User-Agent": "agent-comms/1.1"}, method="DELETE")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                return resp.status in (200, 204)
        except Exception as e:
            logger.debug(f"Failed to delete capsule {cid}: {e}")
            return False


class StorageServerProvider(RelayCloudProvider):
    name = "storage"
