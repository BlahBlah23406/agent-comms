"""
Capsule Storage Backend
=======================
Manages saving, listing, synchronizing, and retrieving Context Capsules locally
and across unified storage servers or cloud providers.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from agent_comms.capsule.cloud.base import CloudCapsuleRecord
from agent_comms.capsule.cloud.factory import get_cloud_provider
from agent_comms.capsule.cloud.relay import StorageServerProvider
from agent_comms.config import config_manager
from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.store")


class CapsuleStore:
    def __init__(
        self,
        base_dir: Optional[Path] = None,
        storage_url: Optional[str] = None,
    ):
        if base_dir is None:
            self.base_dir = (Path.home() / ".agent-comms" / "capsules").resolve()
        else:
            self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

        self.storage_url = (
            storage_url
            or os.environ.get("AGENT_COMMS_STORAGE_URL")
            or config_manager.get("storage_server_url")
            or config_manager.get("default_relay_url")
        )

    def save(
        self,
        capsule: ContextCapsule,
        push_remote: Optional[bool] = None,
    ) -> Path:
        """
        Saves both the raw JSON capsule and companion Markdown briefing locally.
        Optionally synchronizes with unified storage server.
        """
        filename_prefix = f"{capsule.task_id}_{capsule.capsule_id}"
        json_path = self.base_dir / f"{filename_prefix}.json"
        md_path = self.base_dir / f"{filename_prefix}.md"

        # Save JSON
        json_path.write_text(capsule.model_dump_json(indent=2), encoding="utf-8")

        # Save Markdown briefing for easy reading
        md_path.write_text(capsule.to_briefing_markdown(), encoding="utf-8")

        # Auto-sync to unified storage server if requested or configured
        should_sync = push_remote if push_remote is not None else bool(config_manager.get("auto_sync_storage"))
        if should_sync and self.storage_url:
            try:
                self.push_to_storage(capsule)
            except Exception as e:
                logger.warning(f"Could not auto-sync capsule {capsule.capsule_id} to storage server: {e}")

        return json_path

    def load_by_id(
        self,
        capsule_or_task_id: str,
        fetch_remote: bool = True,
    ) -> Optional[ContextCapsule]:
        """
        Finds and loads a capsule by capsule_id or task_id.
        Searches locally first; if not found and fetch_remote is True,
        queries the unified storage server.
        """
        # Exact match / local file check first
        for path in self.base_dir.glob("*.json"):
            if capsule_or_task_id in path.name:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return ContextCapsule.model_validate(data)
                except Exception:
                    continue

        # If not found locally, attempt to pull from unified storage server
        if fetch_remote and self.storage_url:
            try:
                remote_cap = self.pull_from_storage(capsule_or_task_id, save_local=True)
                if remote_cap:
                    return remote_cap
            except Exception as e:
                logger.debug(f"Remote storage pull failed for '{capsule_or_task_id}': {e}")

        return None

    def load_from_file(self, file_path: Path) -> ContextCapsule:
        data = json.loads(file_path.read_text(encoding="utf-8"))
        return ContextCapsule.model_validate(data)

    def list_capsules(self, include_remote: bool = False) -> List[ContextCapsule]:
        """
        Lists capsules stored locally. If include_remote is True, merges
        with available capsules from the unified storage server.
        """
        local_caps: Dict[str, ContextCapsule] = {}
        for path in sorted(self.base_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                cap = ContextCapsule.model_validate(data)
                local_caps[cap.capsule_id] = cap
            except Exception:
                continue

        if include_remote and self.storage_url:
            try:
                remote_records = self.list_storage_capsules()
                for rec in remote_records:
                    if rec.capsule_id not in local_caps:
                        try:
                            remote_cap = self.pull_from_storage(rec.capsule_id, save_local=True)
                            local_caps[remote_cap.capsule_id] = remote_cap
                        except Exception:
                            continue
            except Exception as e:
                logger.debug(f"Could not list remote capsules: {e}")

        return list(local_caps.values())

    # --- Unified Storage Server Integration ---

    def push_to_storage(self, capsule_or_id: Union[str, ContextCapsule]) -> str:
        """Pushes a local capsule to the unified storage server."""
        if isinstance(capsule_or_id, ContextCapsule):
            capsule = capsule_or_id
        else:
            p = Path(capsule_or_id)
            if p.exists() and p.is_file():
                capsule = self.load_from_file(p)
            else:
                capsule = self.load_by_id(capsule_or_id, fetch_remote=False)
            if not capsule:
                raise FileNotFoundError(f"Capsule '{capsule_or_id}' not found locally to push.")

        provider = StorageServerProvider(storage_url=self.storage_url)
        location = provider.upload(capsule)
        logger.info(f"Capsule '{capsule.capsule_id}' pushed to unified storage server: {location}")
        return location

    def pull_from_storage(
        self,
        capsule_id_or_uri: str,
        save_local: bool = True,
    ) -> ContextCapsule:
        """Downloads a capsule from the unified storage server."""
        provider = StorageServerProvider(storage_url=self.storage_url)
        capsule = provider.download(capsule_id_or_uri)
        if save_local:
            self.save(capsule, push_remote=False)
        logger.info(f"Capsule '{capsule.capsule_id}' pulled from unified storage server")
        return capsule

    def list_storage_capsules(
        self,
        query: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[CloudCapsuleRecord]:
        """Queries the unified storage server for available capsules."""
        provider = StorageServerProvider(storage_url=self.storage_url)
        return provider.list_capsules(query=query, task_id=task_id)

    def sync(self, direction: str = "both") -> Dict[str, List[str]]:
        """
        Synchronizes capsules between local storage and unified storage server.
        direction: 'both', 'push', or 'pull'
        """
        pushed: List[str] = []
        pulled: List[str] = []

        provider = StorageServerProvider(storage_url=self.storage_url)
        remote_records = {r.capsule_id: r for r in provider.list_capsules()}
        local_caps = {c.capsule_id: c for c in self.list_capsules(include_remote=False)}

        # Push local -> remote
        if direction in ("both", "push"):
            for cid, cap in local_caps.items():
                if cid not in remote_records:
                    provider.upload(cap)
                    pushed.append(cid)

        # Pull remote -> local
        if direction in ("both", "pull"):
            for cid, rec in remote_records.items():
                if cid not in local_caps:
                    try:
                        remote_cap = provider.download(cid)
                        self.save(remote_cap, push_remote=False)
                        pulled.append(cid)
                    except Exception as e:
                        logger.warning(f"Error pulling capsule {cid} during sync: {e}")

        logger.info(f"Unified Storage Sync complete: {len(pushed)} pushed, {len(pulled)} pulled")
        return {"pushed": pushed, "pulled": pulled}

    # --- Cloud Storage Integration ---

    def push_to_cloud(
        self,
        capsule_or_id: Union[str, ContextCapsule],
        provider_name: Optional[str] = None,
        **kwargs,
    ) -> str:
        """
        Uploads a local capsule to the specified or default cloud/storage provider.
        Returns the cloud URI or identifier.
        """
        if isinstance(capsule_or_id, ContextCapsule):
            capsule = capsule_or_id
        else:
            p = Path(capsule_or_id)
            if p.exists() and p.is_file():
                capsule = self.load_from_file(p)
            else:
                capsule = self.load_by_id(capsule_or_id, fetch_remote=False)
            if not capsule:
                raise FileNotFoundError(f"Capsule '{capsule_or_id}' not found locally to push.")

        provider = get_cloud_provider(provider_name, **kwargs)
        location = provider.upload(capsule)
        logger.info("Capsule '%s' pushed via %s: %s", capsule.capsule_id, provider.name, location)
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
        if "://" in capsule_id_or_uri and not provider_name:
            scheme = capsule_id_or_uri.split("://", 1)[0].lower()
            if scheme in ("s3", "gs", "azure", "github", "relay", "storage"):
                provider_name = "gcs" if scheme == "gs" else scheme

        provider = get_cloud_provider(provider_name, **kwargs)
        capsule = provider.download(capsule_id_or_uri)
        if save_local:
            self.save(capsule, push_remote=False)
        logger.info("Capsule '%s' pulled from %s", capsule.capsule_id, provider.name)
        return capsule

    def list_cloud_capsules(
        self,
        provider_name: Optional[str] = None,
        **kwargs,
    ) -> List[CloudCapsuleRecord]:
        """
        Queries cloud or unified storage provider for available remote capsules.
        """
        provider = get_cloud_provider(provider_name, **kwargs)
        return provider.list_capsules()
