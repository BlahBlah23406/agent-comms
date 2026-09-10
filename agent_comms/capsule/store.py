"""
Capsule Storage Backend
=======================
Manages saving, listing, and retrieving context capsules locally or remotely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional
from agent_comms.models.capsule import ContextCapsule


class CapsuleStore:
    def __init__(self, base_dir: Optional[Path] = None):
        if base_dir is None:
            self.base_dir = Path.home() / ".agent-comms" / "capsules"
        else:
            self.base_dir = base_dir.resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def save(self, capsule: ContextCapsule) -> Path:
        """
        Saves both the raw JSON capsule and a companion Markdown briefing.
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
        Finds and loads a capsule by capsule_id or task_id.
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
