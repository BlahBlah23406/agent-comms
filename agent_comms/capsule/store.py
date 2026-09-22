"""
Capsule Storage Backend
=======================
Manages saving, listing, and retrieving context capsules locally or across cloud providers.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import List, Optional, Union

from agent_comms.capsule.cloud.base import CloudCapsuleRecord
from agent_comms.capsule.cloud.factory import get_cloud_provider
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.store")


class CapsuleStore:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            self.base_dir = Path.home() / ".agent-comms" / "capsules"
        else:
            self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, capsule: ContextCapsule) -> Path:
        """
        Saves both the raw JSON capsule and a companion Markdown briefing locally.
        """
        filename_prefix = f"{capsule.task_id}_{capsule.capsule_id}"
        json_path = self.base_dir / f"{filename_prefix}.json"
        md_path = self.base_dir / f"{filename_prefix}.md"

        # Save JSON
        json_path.write_text(capsule.model_dump_json(indent=2), encoding="utf-8")

        # Save Markdown briefing for easy reading
        md_path.write_text(capsule.to_briefing_markdown(), encoding="utf-8")

        return json_path

    def load_by_id(self, capsule_or_task_id: str) -> Optional[ContextCapsule]:
        """
        Finds and loads a capsule by capsule_id or task_id from local store.
        """
        # Exact match check first
        for path in self.base_dir.glob("*.json"):
            if capsule_or_task_id in path.name:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return ContextCapsule.model_validate(data)
                except Exception:
                    continue
        return None

    def load_from_file(self, file_path: Path) -> ContextCapsule:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return ContextCapsule.model_validate(data)

    def list_capsules(self) -> List[ContextCapsule]:
        capsules = []
        for path in sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                capsules.append(ContextCapsule.model_validate(data))
            except Exception:
                continue
        return capsules

    # --- Cloud Storage Integration ---

    def push_to_cloud(
        self,
        capsule_or_id: Union[str, ContextCapsule],
        provider_name: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Uploads a local capsule to the specified or default cloud provider.
        Returns the cloud URI or identifier.
        """
        if isinstance(capsule_or_id, ContextCapsule):
            capsule = capsule_or_id
        else:
            p = Path(capsule_or_id)
            if p.exists() and p.is_file():
                capsule = self.load_from_file(p)
            else:
                capsule = self.load_by_id(capsule_or_id)
            if not capsule:
                raise FileNotFoundError(f"Capsule '{capsule_or_id}' not found locally to push.")

        provider = get_cloud_provider(provider_name, **kwargs)
        location = provider.upload(capsule)
        logger.info("Capsule '%s' pushed to cloud via %s: %s", capsule.capsule_id, provider.name, location)
        return location

    def pull_from_cloud(
        self,
        capsule_id_or_uri: str,
        provider_name: Optional[str] = None,
        save_local: bool = True,
        **kwargs,
    ) -> ContextCapsule:
        """
        Downloads a capsule from cloud storage, optionally persists it to local store,
        and returns the validated ContextCapsule.
        """
        # If URI format indicates provider, extract it
        if "://" in capsule_id_or_uri and not provider_name:
            scheme = capsule_id_or_uri.split("://", 1)[0].lower()
            if scheme in ("s3", "gs", "azure", "github", "relay"):
                provider_name = "gcs" if scheme == "gs" else scheme

        provider = get_cloud_provider(provider_name, **kwargs)
        capsule = provider.download(capsule_id_or_uri)
        if save_local:
            self.save(capsule)
        logger.info("Capsule '%s' pulled from %s", capsule.capsule_id, provider.name)
        return capsule

    def list_cloud_capsules(
        self,
        provider_name: Optional[str] = None,
        **kwargs,
    ) -> List[CloudCapsuleRecord]:
        """
        Queries the cloud provider for available remote capsules.
        """
        provider = get_cloud_provider(provider_name, **kwargs)
        return provider.list_capsules()
