"""
Relay Hub Cloud Storage Provider
================================
Stores and retrieves Context Capsules directly via the AHRP Relay's REST API.
Zero dependencies required (uses standard library urllib).
Ideal for local network, self-hosted relay servers, or team brokers.
"""

from __future__ import annotations

import json
import logging
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

from agent_comms.capsule.cloud.base import BaseCloudProvider, CloudCapsuleRecord
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.cloud.relay")


class RelayCloudProvider(BaseCloudProvider):
    name = "relay"

    def __init__(self, relay_url: Optional[str] = None):
        raw_url = relay_url or config_manager.get("default_relay_url", "http://localhost:8765")
        # Convert ws/wss to http/https for REST endpoints
        if raw_url.startswith("ws://"):
            raw_url = "http://" + raw_url[5:]
        elif raw_url.startswith("wss://"):
            raw_url = "https://" + raw_url[6:]
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
            headers={"Content-Type": "application/json", "User-Agent": "agent-comms/1.0"},
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                cid = result.get("capsule_id", capsule.capsule_id)
                uri = f"relay://{self.base_url}/capsules/{cid}"
                logger.info("Uploaded capsule '%s' to relay: %s", cid, uri)
                return uri
        except urllib.error.URLError as e:
            raise RuntimeError(f"Failed to upload capsule to relay ({self.base_url}): {e}")

    def download(self, capsule_id_or_uri: str) -> ContextCapsule:
        cid = capsule_id_or_uri
        if cid.startswith("relay://"):
            cid = cid.split("/")[-1]

        url = f"{self.base_url}/capsules/{cid}"
        req = urllib.request.Request(url, headers={"User-Agent": "agent-comms/1.0"}, method="GET")

        try:
            with urllib.request.urlopen(req, timeout=10.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                return ContextCapsule.model_validate(data)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                raise FileNotFoundError(f"Capsule '{cid}' not found on relay at {self.base_url}")
            raise RuntimeError(f"Relay error ({e.code}): {e.reason}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"Could not connect to relay at {self.base_url}: {e}")

    def list_capsules(self) -> List[CloudCapsuleRecord]:
        # If relay provides list endpoint, fetch it; otherwise return empty or query peers
        url = f"{self.base_url}/capsules"
        req = urllib.request.Request(url, headers={"User-Agent": "agent-comms/1.0"}, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                items = json.loads(resp.read().decode("utf-8"))
                records = []
                for item in items:
                    records.append(
                        CloudCapsuleRecord(
                            capsule_id=item.get("capsule_id", "unknown"),
                            task_id=item.get("task_id", "unknown"),
                            created_at=item.get("created_at", ""),
                            summary=item.get("executive_summary", ""),
                            provider="relay",
                            location=f"relay://{self.base_url}/capsules/{item.get('capsule_id')}",
                        )
                    )
                return records
        except Exception:
            return []

    def delete(self, capsule_id_or_uri: str) -> bool:
        return True
