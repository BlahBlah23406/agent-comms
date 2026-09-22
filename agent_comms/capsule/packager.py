"""
Context Capsule Packager
========================
Extracts epistemic context, task graph, git state, diffs, and untracked files
to create a fully self-contained ContextCapsule.
"""

from __future__ import annotations

import os
import platform
import socket
from pathlib import Path
from typing import Dict, List, Optional
from agent_comms.capsule.git_sync import GitHelper
from agent_comms.capsule.store import CapsuleStore
from agent_comms.models.capsule import (
    AgentMetadata,
    ContextCapsule,
    EpistemicLearning,
    LearningCategory,
    StepStatus,
    TaskGraph,
    TaskStep,
    WorkspacePatch,
)


class CapsulePackager:
    def __init__(self, workspace_path: Optional[Path] = None, store: Optional[CapsuleStore] = None):
        self.workspace_path = (workspace_path or Path.cwd()).resolve()
        self.git = GitHelper(self.workspace_path)
        self.store = store or CapsuleStore()

    def package(
        self,
        task_id: str,
        title: str,
        executive_summary: str,
        goal: str,
        steps: Optional[List[TaskStep]] = None,
        next_action: Optional[str] = None,
        epistemic_learnings: Optional[List[EpistemicLearning]] = None,
        agent_name: str = "DeveloperAgent",
        session_id: Optional[str] = None,
        resumption_prompt: Optional[str] = None,
        target_agent: Optional[str] = None,
    ) -> ContextCapsule:
        """
        Packages current workspace state into a ContextCapsule.
        """
        # 1. Collect Agent Metadata
        generator = AgentMetadata(
            agent_name=agent_name,
            agent_version="1.0.0",
            machine_id=socket.gethostname(),
            os_name=platform.system(),
            session_id=session_id,
        )

        # 2. Build Task Graph
        task_graph = TaskGraph(
            goal=goal,
            steps=steps or [],
            next_action=next_action,
        )

        # 3. Capture Workspace State
        is_git = self.git.is_git_repo()
        workspace_patch = WorkspacePatch(
            is_git_repo=is_git,
            repo_root=str(self.git.get_repo_root()) if is_git else str(self.workspace_path),
            branch_name=self.git.get_current_branch() if is_git else None,
            base_commit=self.git.get_head_commit() if is_git else None,
            git_diff=self.git.get_git_diff() if is_git else None,
            untracked_files=self.git.get_untracked_files(),
            modified_files=self.git.get_modified_files() if is_git else [],
        )

        # 4. Synthesize Default Resumption Prompt if not explicitly provided
        if not resumption_prompt:
            prompt_parts = [
                f"You are continuing task '{task_id}': {title}.",
                f"Previous status: {executive_summary}",
            ]
            if next_action:
                prompt_parts.append(f"Your immediate next instruction: {next_action}")
            if epistemic_learnings:
                prompt_parts.append(
                    "Be mindful of the discovered epistemic learnings and constraints in your briefing."
                )
            resumption_prompt = " ".join(prompt_parts)

        # 5. Assemble Capsule
        capsule = ContextCapsule(
            task_id=task_id,
            title=title,
            generator=generator,
            target_agent=target_agent,
            executive_summary=executive_summary,
            task_graph=task_graph,
            epistemic_learnings=epistemic_learnings or [],
            workspace=workspace_patch,
            resumption_prompt=resumption_prompt,
        )

        return capsule
