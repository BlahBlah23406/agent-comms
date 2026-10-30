"""
Unified Capsule Storage Server
==============================
High-performance REST API and persistent disk storage engine for Context Capsules.
Allows any agent or machine in the fleet to store, query, retrieve, and synchronize
capsules across the private Tailscale network.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware

from agent_comms.models.capsule import ContextCapsule

logger = logging.getLogger("agent_comms.capsule.server")


class CapsuleStorageServer:
    """Storage engine and index for Context Capsules (in-memory or persistent disk)."""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = Path(storage_dir).resolve() if storage_dir is not None else None
        if self.storage_dir:
            self.storage_dir.mkdir(parents=True, exist_ok=True)

        # In-memory index: capsule_id -> metadata dictionary
        self._index: Dict[str, Dict[str, Any]] = {}
        # In-memory raw capsule cache (used when storage_dir is None)
        self._memory_data: Dict[str, Dict[str, Any]] = {}
        # task_id -> list of capsule_ids
        self._task_index: Dict[str, List[str]] = {}

        if self.storage_dir:
            self.reload_index()

    def reload_index(self):
        """Scans storage directory and indexes all existing capsules."""
        self._index.clear()
        self._task_index.clear()
        if not self.storage_dir:
            return

        for json_path in sorted(self.storage_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
            try:
                stat = json_path.stat()
                data = json.loads(json_path.read_text(encoding="utf-8"))
                cid = data.get("capsule_id")
                tid = data.get("task_id", "unknown")
                if not cid:
                    stem = json_path.stem
                    cid = stem.split("_")[-1] if "_" in stem else stem

                title = data.get("title") or tid
                summary = data.get("executive_summary") or ""
                created_at = data.get("created_at") or ""
                gen = data.get("generator") or {}

                rec = {
                    "capsule_id": cid,
                    "task_id": tid,
                    "title": title,
                    "executive_summary": summary,
                    "created_at": created_at,
                    "agent_name": gen.get("agent_name", "unknown"),
                    "machine_id": gen.get("machine_id", "unknown"),
                    "target_agent": data.get("target_agent"),
                    "file_name": json_path.name,
                    "size_bytes": stat.st_size,
                    "mtime": stat.st_mtime,
                }
                self._index[cid] = rec
                self._task_index.setdefault(tid, []).append(cid)
            except Exception as e:
                logger.warning(f"Failed to index capsule file {json_path}: {e}")

        logger.info(f"Indexed {len(self._index)} capsules from {self.storage_dir}")

    def store_capsule(self, raw_data: Dict[str, Any]) -> Dict[str, Any]:
        """Validates and persists a capsule to disk (or memory)."""
        capsule = ContextCapsule.model_validate(raw_data)
        cid = capsule.capsule_id
        tid = capsule.task_id

        rec = {
            "capsule_id": cid,
            "task_id": tid,
            "title": capsule.title or tid,
            "executive_summary": capsule.executive_summary or "",
            "created_at": capsule.created_at,
            "agent_name": capsule.generator.agent_name,
            "machine_id": capsule.generator.machine_id,
            "target_agent": capsule.target_agent,
            "size_bytes": len(capsule.model_dump_json().encode("utf-8")),
            "mtime": 0.0,
        }

        if self.storage_dir:
            filename_prefix = f"{tid}_{cid}"
            json_path = self.storage_dir / f"{filename_prefix}.json"
            md_path = self.storage_dir / f"{filename_prefix}.md"

            tmp_json = json_path.with_suffix(".json.tmp")
            tmp_md = md_path.with_suffix(".md.tmp")

            tmp_json.write_text(capsule.model_dump_json(indent=2), encoding="utf-8")
            tmp_md.write_text(capsule.to_briefing_markdown(), encoding="utf-8")

            tmp_json.replace(json_path)
            tmp_md.replace(md_path)

            stat = json_path.stat()
            rec["file_name"] = json_path.name
            rec["size_bytes"] = stat.st_size
            rec["mtime"] = stat.st_mtime
        else:
            self._memory_data[cid] = capsule.model_dump()
            import time
            rec["mtime"] = time.time()

        self._index[cid] = rec
        if cid not in self._task_index.setdefault(tid, []):
            self._task_index[tid].append(cid)

        logger.info(f"Stored capsule {cid} for task {tid}")
        return rec

    def get_capsule(self, capsule_id_or_task_id: str) -> Optional[Dict[str, Any]]:
        """Finds and returns raw capsule data by capsule_id or task_id."""
        cid = capsule_id_or_task_id

        if not self.storage_dir:
            if cid in self._memory_data:
                return self._memory_data[cid]
            if cid in self._task_index and self._task_index[cid]:
                latest_cid = self._task_index[cid][0]
                return self._memory_data.get(latest_cid)
            return None

        # Check direct capsule_id in disk index
        if cid in self._index:
            rec = self._index[cid]
            path = self.storage_dir / rec.get("file_name", "")
            if path.exists():
                return json.loads(path.read_text(encoding="utf-8"))

        # Check by task_id in disk index
        if cid in self._task_index and self._task_index[cid]:
            latest_cid = self._task_index[cid][0]
            rec = self._index.get(latest_cid)
            if rec:
                path = self.storage_dir / rec.get("file_name", "")
                if path.exists():
                    return json.loads(path.read_text(encoding="utf-8"))

        # Fallback to filesystem scan for partial matches
        for path in self.storage_dir.glob("*.json"):
            if capsule_id_or_task_id in path.name:
                try:
                    data = json.loads(path.read_text(encoding="utf-8"))
                    return data
                except Exception:
                    continue

        return None

    def get_briefing(self, capsule_id_or_task_id: str) -> Optional[str]:
        """Finds and returns markdown briefing content."""
        capsule_data = self.get_capsule(capsule_id_or_task_id)
        if not capsule_data:
            return None

        if self.storage_dir:
            cid = capsule_data.get("capsule_id")
            tid = capsule_data.get("task_id", "unknown")
            filename_prefix = f"{tid}_{cid}"
            md_path = self.storage_dir / f"{filename_prefix}.md"
            if md_path.exists():
                return md_path.read_text(encoding="utf-8")

        # Generate on the fly
        capsule = ContextCapsule.model_validate(capsule_data)
        return capsule.to_briefing_markdown()

    def list_capsules(
        self,
        query: Optional[str] = None,
        task_id: Optional[str] = None,
        target_agent: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """Returns indexed capsule records matching criteria, newest first."""
        records = sorted(self._index.values(), key=lambda r: r.get("mtime", 0), reverse=True)

        if task_id:
            records = [r for r in records if r.get("task_id") == task_id]

        if target_agent:
            records = [r for r in records if (r.get("target_agent") or "").lower() == target_agent.lower()]

        if query:
            q = query.lower()
            records = [
                r for r in records
                if q in r.get("capsule_id", "").lower()
                or q in r.get("task_id", "").lower()
                or q in r.get("title", "").lower()
                or q in r.get("executive_summary", "").lower()
            ]

        return records[:limit]

    def delete_capsule(self, capsule_id_or_task_id: str) -> bool:
        """Deletes a capsule from storage."""
        target_cid = None
        if capsule_id_or_task_id in self._index:
            target_cid = capsule_id_or_task_id
        elif capsule_id_or_task_id in self._task_index and self._task_index[capsule_id_or_task_id]:
            target_cid = self._task_index[capsule_id_or_task_id][0]

        if not target_cid:
            return False

        rec = self._index.pop(target_cid, None)
        self._memory_data.pop(target_cid, None)
        tid = rec.get("task_id") if rec else None
        if tid and tid in self._task_index:
            self._task_index[tid] = [c for c in self._task_index[tid] if c != target_cid]

        deleted = True
        if self.storage_dir and rec and "file_name" in rec:
            json_path = self.storage_dir / rec["file_name"]
            md_path = json_path.with_suffix(".md")
            if json_path.exists():
                json_path.unlink()
            if md_path.exists():
                md_path.unlink()

        return deleted

    def get_status(self) -> Dict[str, Any]:
        """Returns server and storage health statistics."""
        total_size = sum(r.get("size_bytes", 0) for r in self._index.values())
        disk_free_mb = 0.0
        if self.storage_dir:
            disk_free_mb = round(shutil.disk_usage(self.storage_dir).free / (1024 * 1024), 2)

        return {
            "status": "healthy",
            "storage_dir": str(self.storage_dir) if self.storage_dir else "in-memory",
            "total_capsules": len(self._index),
            "total_size_bytes": total_size,
            "disk_free_mb": disk_free_mb,
        }


def create_storage_app(
    storage_server: Optional[CapsuleStorageServer] = None,
    storage_dir: Optional[Path] = None,
    title: str = "Agent Comms Unified Capsule Storage Server",
) -> FastAPI:
    """Factory creating the FastAPI app for Unified Capsule Storage."""
    app = FastAPI(
        title=title,
        version="1.1.0",
        description="Unified Context Capsule storage server for cross-machine AI agent fleets.",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    if storage_server is None:
        storage_server = CapsuleStorageServer(storage_dir=storage_dir)
    app.state.storage = storage_server

    @app.get("/health")
    async def health():
        return app.state.storage.get_status()

    @app.get("/storage/status")
    async def storage_status():
        return app.state.storage.get_status()

    @app.get("/capsules")
    async def list_capsules(
        q: Optional[str] = Query(None, description="Search term across title, summary, or IDs"),
        task_id: Optional[str] = Query(None, description="Filter by task ID"),
        target_agent: Optional[str] = Query(None, description="Filter by target agent name"),
        limit: int = Query(100, ge=1, le=500),
    ):
        return app.state.storage.list_capsules(query=q, task_id=task_id, target_agent=target_agent, limit=limit)

    @app.post("/capsules")
    async def upload_capsule(capsule: Dict[str, Any]):
        cid = capsule.get("capsule_id")
        if not cid:
            raise HTTPException(status_code=400, detail="Missing capsule_id in request body")
        try:
            rec = app.state.storage.store_capsule(capsule)
            return {
                "status": "stored",
                "capsule_id": rec["capsule_id"],
                "task_id": rec["task_id"],
                "location": f"/capsules/{rec['capsule_id']}",
            }
        except Exception as e:
            logger.error(f"Error storing capsule: {e}")
            raise HTTPException(status_code=400, detail=f"Failed to store capsule: {e}")

    @app.get("/capsules/{capsule_id}")
    async def get_capsule(capsule_id: str):
        data = app.state.storage.get_capsule(capsule_id)
        if not data:
            raise HTTPException(status_code=404, detail=f"Capsule '{capsule_id}' not found")
        return data

    @app.get("/capsules/{capsule_id}/briefing")
    async def get_briefing(capsule_id: str):
        briefing = app.state.storage.get_briefing(capsule_id)
        if briefing is None:
            raise HTTPException(status_code=404, detail=f"Capsule briefing for '{capsule_id}' not found")
        return Response(content=briefing, media_type="text/markdown")

    @app.delete("/capsules/{capsule_id}")
    async def delete_capsule(capsule_id: str):
        success = app.state.storage.delete_capsule(capsule_id)
        if not success:
            raise HTTPException(status_code=404, detail=f"Capsule '{capsule_id}' not found to delete")
        return {"status": "deleted", "capsule_id": capsule_id}

    return app
