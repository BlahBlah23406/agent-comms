"""
Context Capsule Unpacker
========================
Restores a ContextCapsule into a workspace by applying patches, writing
untracked files, and returning the structured briefing and resumption prompt.
"""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional, Tuple
from agent_comms.capsule.git_sync import GitHelper
from agent_comms.models.capsule import ContextCapsule


class CapsuleUnpacker:
    def __init__(self, workspace_path: Optional[Path] = None):
        self.workspace_path = (workspace_path or Path.cwd()).resolve()
        self.git = GitHelper(self.workspace_path)

    def apply(
        self,
        capsule: ContextCapsule,
        apply_workspace: bool = True,
        overwrite_untracked: bool = True,
    ) -> Dict[str, any]:
        """
        Applies a capsule to the current workspace.
        Returns a dict containing restoration details and briefing text.
        """
        result = {
            "capsule_id": capsule.capsule_id,
            "task_id": capsule.task_id,
            "briefing_markdown": capsule.to_briefing_markdown(),
            "resumption_prompt": capsule.resumption_prompt,
            "git_patch_applied": False,
            "git_patch_message": "Skipped",
            "untracked_files_restored": [],
        }

        if not apply_workspace:
            return result

        # 1. Apply git patch if git repo and diff present
        if capsule.workspace.git_diff:
            success, msg = self.git.apply_patch(capsule.workspace.git_diff)
            result["git_patch_applied"] = success
            result["git_patch_message"] = msg
        else:
            result["git_patch_applied"] = True
            result["git_patch_message"] = "No git patch to apply."

        # 2. Restore untracked files
        if capsule.workspace.untracked_files:
            written = self.git.write_untracked_files(
                capsule.workspace.untracked_files, overwrite=overwrite_untracked
            )
            result["untracked_files_restored"] = written

        return result
